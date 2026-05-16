"""
MAIHERA Presence Health Worker
Monitors Presence deployment health.

Scope (deliberately narrow):
- Triggered by GitHub push events to Presence main branch
- Fires one HTTP smoke test against the Presence live URL
- Surfaces a nudge if the URL returns non-200
- Does NOT poll on a schedule — event-driven only
- Does NOT monitor platform status (Vercel/Supabase) —
  platform outages are not actionable

The GitHubWorker already polls for new commits. This worker
listens for a signal from GitHubWorker after a Presence push
is detected and runs the smoke test then.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError
import urllib.request

logger = logging.getLogger(__name__)

# Presence live URL — the root endpoint to smoke test
PRESENCE_URL = "https://presence-beta.vercel.app"

# HTTP timeout in seconds
SMOKE_TEST_TIMEOUT = 10

# Minimum seconds between smoke tests — prevents rapid retriggers
# if multiple commits land in quick succession
COOLDOWN_SECONDS = 300  # 5 minutes


class PresenceHealthWorker:
    """
    Event-driven Presence deployment health monitor.

    Usage:
        worker = PresenceHealthWorker(brain_service, voice_service)
        worker.set_ws_manager(ws_manager)

        # Called by GitHubWorker when a Presence push is detected:
        await worker.on_presence_push(commit_sha, commit_message)
    """

    def __init__(self, brain_service, voice_service=None):
        self._brain = brain_service
        self._voice = voice_service
        self._ws_manager = None
        self._last_test_at: Optional[float] = None
        self._running = False
        logger.info("PresenceHealthWorker initialized.")

    def set_ws_manager(self, ws_manager) -> None:
        self._ws_manager = ws_manager

    def set_voice_service(self, voice_service) -> None:
        self._voice = voice_service

    # ── Entry Point ───────────────────────────────────────────────

    async def on_presence_push(
        self,
        commit_sha: str,
        commit_message: str,
    ) -> None:
        """
        Called when GitHubWorker detects a new push to
        Presence main branch. Runs the smoke test after
        a short delay to allow Vercel deployment to complete.
        """
        import time
        now = time.monotonic()

        # Cooldown — ignore if tested recently
        if (
            self._last_test_at is not None
            and now - self._last_test_at < COOLDOWN_SECONDS
        ):
            logger.debug(
                "PresenceHealth: cooldown active — skipping smoke test."
            )
            return

        logger.info(
            "PresenceHealth: push detected — SHA %s. "
            "Waiting 60s for Vercel deployment...",
            commit_sha[:8]
        )

        # Wait for Vercel to finish deploying before testing
        await asyncio.sleep(60)

        self._last_test_at = time.monotonic()
        await self._run_smoke_test(commit_sha, commit_message)

    # ── Smoke Test ────────────────────────────────────────────────

    async def _run_smoke_test(
        self,
        commit_sha: str,
        commit_message: str,
    ) -> None:
        """
        Run HTTP GET against PRESENCE_URL.
        Surface a nudge if non-200 or unreachable.
        Log result either way.
        """
        logger.info(
            "PresenceHealth: smoke testing %s ...", PRESENCE_URL
        )

        # Run blocking HTTP call in executor to avoid blocking loop
        loop = asyncio.get_event_loop()
        try:
            status_code = await loop.run_in_executor(
                None,
                self._http_get,
                PRESENCE_URL,
            )
        except Exception as e:
            logger.error(
                "PresenceHealth: smoke test executor error: %s", e
            )
            status_code = None

        if status_code == 200:
            logger.info(
                "PresenceHealth: Presence is healthy — "
                "HTTP 200 after push %s.",
                commit_sha[:8]
            )
            # No nudge on success — only surface problems
            return

        # Non-200 or unreachable — surface to Yash
        if status_code is None:
            problem = "unreachable"
            detail  = "the URL did not respond within 10 seconds"
        else:
            problem = f"returning HTTP {status_code}"
            detail  = f"expected 200, got {status_code}"

        nudge_text = (
            f"Boss, Presence is {problem} after your latest push. "
            f"Commit: '{commit_message[:60]}'. "
            f"Worth checking — {detail}."
        )

        logger.warning(
            "PresenceHealth: Presence is %s after push %s.",
            problem, commit_sha[:8]
        )

        # Create an issue node in the brain
        self._create_health_issue_node(
            commit_sha=commit_sha,
            commit_message=commit_message,
            status_code=status_code,
            problem=problem,
        )

        # Surface via voice and WebSocket
        if self._voice:
            await self._voice.enqueue_speech(
                text=nudge_text,
                node_ids=[],
                priority="urgent",
            )

        if self._ws_manager:
            await self._ws_manager.send_maihera_speak(
                text=nudge_text,
                node_ids=[],
                priority="urgent",
            )

    def _http_get(self, url: str) -> Optional[int]:
        """
        Blocking HTTP GET. Returns status code or None on error.
        Runs in executor — never call directly from async context.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MAIHERA-HealthCheck/1.0"},
            )
            with urlopen(req, timeout=SMOKE_TEST_TIMEOUT) as response:
                return response.status
        except URLError as e:
            logger.warning("PresenceHealth: URLError — %s", e)
            return None
        except Exception as e:
            logger.warning("PresenceHealth: HTTP error — %s", e)
            return None

    # ── Brain Integration ─────────────────────────────────────────

    def _create_health_issue_node(
        self,
        commit_sha: str,
        commit_message: str,
        status_code: Optional[int],
        problem: str,
    ) -> None:
        """
        Create an issue node in the brain when Presence is unhealthy.
        Deduplicates by source_ref so repeated failures
        update the existing node rather than creating duplicates.
        """
        try:
            source_ref = f"presence_health_{commit_sha[:8]}"

            # Check for existing node
            existing = self._brain.find_node_by_source_ref(source_ref)
            if existing:
                self._brain.update_node(
                    existing["id"],
                    {
                        "description": (
                            f"Presence returned {problem} after push. "
                            f"Commit: {commit_message[:80]}. "
                            f"Detected: {datetime.now(timezone.utc).isoformat()}"
                        ),
                        "attention": 0.9,
                    }
                )
                return

            # Find Presence project node
            projects = self._brain.list_nodes(node_type="project")
            presence_project = next(
                (p for p in projects
                 if "presence" in p.get("label", "").lower()),
                None,
            )
            project_id = (
                presence_project["id"] if presence_project else None
            )

            node_data = {
                "id":          _new_uuid(),
                "type":        "issue",
                "label":       f"Presence deployment issue — {commit_sha[:8]}",
                "description": (
                    f"Presence returned {problem} after push. "
                    f"Commit: {commit_message[:80]}. "
                    f"HTTP status: {status_code}. "
                    f"Detected: {datetime.now(timezone.utc).isoformat()}"
                ),
                "project_id":  project_id,
                "source":      "system",
                "source_ref":  source_ref,
                "status":      "active",
                "workspace":   "personal",
                "importance":  0.8,
                "attention":   0.9,
                "resistance":  0.0,
                "is_stale":    False,
                "node_weight": 0.9,
            }

            self._brain.create_node(node_data)
            logger.info(
                "PresenceHealth: issue node created for %s.",
                commit_sha[:8]
            )

        except Exception as e:
            logger.error(
                "PresenceHealth: failed to create issue node: %s", e
            )


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())