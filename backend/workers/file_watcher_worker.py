"""
MAIHERA File Watcher Worker
Async consumer for FileChangeEvents from the FileWatcherService.
Translates file activity into brain signal updates.
Combined with system observer context to confirm Yash attribution.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum seconds between attention updates for the same project
# Prevents rapid file saves from flooding signal writes
DEBOUNCE_SECONDS = 30

# Attention boost on file activity
FILE_ACTIVITY_BOOST = 0.10


class FileWatcherWorker:
    """
    Consumes FileChangeEvents and writes attention boosts
    to matching project nodes.

    Attribution rule: only writes signals if the system observer
    currently reports a whitelisted app in focus (coding or design).
    This prevents family file activity from corrupting signals.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        brain_service,
        observer_worker=None,
    ):
        self._queue = event_queue
        self._brain = brain_service
        self._observer_worker = observer_worker
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Debounce: project_id → last signal write timestamp
        self._last_write: dict[str, float] = {}

        logger.info("FileWatcherWorker initialized.")

    def set_observer_worker(self, observer_worker) -> None:
        """Wire in the system observer for attribution checks."""
        self._observer_worker = observer_worker

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(
            self._consume_loop(),
            name="FileWatcherWorker"
        )
        logger.info("FileWatcherWorker started.")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("FileWatcherWorker stopped.")

    # ── Consumer Loop ─────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        logger.info("FileWatcherWorker: consumer loop running.")
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
                await self._handle_event(event)
                self._queue.task_done()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("FileWatcherWorker: consumer cancelled.")
                break
            except Exception as e:
                logger.error(
                    "FileWatcherWorker: error handling event: %s", e
                )

    # ── Event Handling ────────────────────────────────────────────

    async def _handle_event(self, event) -> None:
        """
        Attribute the file change to Yash if a whitelisted app
        is in foreground. Then boost attention on the matching
        project node.
        """
        # Attribution check — is this Yash or someone else?
        if not self._is_yash_active():
            logger.debug(
                "FileWatcher: ignoring event — "
                "no whitelisted app in foreground. file=%s",
                event.filename
            )
            return

        logger.debug(
            "FileWatcher: %s — %s (folder: %s)",
            event.event_type, event.filename, event.folder
        )

        # Match file's folder to a project node
        project = self._match_project(event.folder)
        if not project:
            logger.debug(
                "FileWatcher: no project match for folder %s",
                event.folder
            )
            return

        project_id = project.get("id")
        if not project_id:
            return

        # Debounce — don't write more than once per 30s per project
        import time
        now = time.monotonic()
        last = self._last_write.get(project_id, 0.0)
        if now - last < DEBOUNCE_SECONDS:
            logger.debug(
                "FileWatcher: debounced signal write for %s",
                project.get("label")
            )
            return

        # Read current attention live from Neo4j
        node = self._brain.get_node(project_id)
        if not node:
            return

        current = float(node.get("attention", 0.0))
        new_val = min(1.0, current + FILE_ACTIVITY_BOOST)

        self._brain.update_signal(project_id, "attention", new_val)
        self._last_write[project_id] = now

        logger.info(
            "FileWatcher: attention %s → %.3f "
            "(file activity: %s)",
            project.get("label"), new_val, event.filename
        )

        # Also update last_touched on self node
        self._update_self_last_active()

    def _is_yash_active(self) -> bool:
        """
        Returns True if the system observer reports a whitelisted
        app currently in foreground.
        Falls back to True if observer not wired (safe default
        during testing).
        """
        if self._observer_worker is None:
            return True

        context = self._observer_worker.current_context
        return context in ("coding", "design", "browsing")

    def _match_project(self, folder: str) -> Optional[dict]:
        """
        Match a file's folder path to a project node.
        Checks if the folder path contains the project name
        or if the project's known paths match.

        Current mapping:
        - paths containing 'presence' → Presence project
        - paths containing 'maihera'  → MAIHERA project
        """
        folder_lower = folder.lower()

        try:
            projects = self._brain.list_nodes(
                node_type="project", status="active"
            )
            for project in projects:
                label_lower = project.get("label", "").lower()
                if label_lower in folder_lower:
                    return project

            # No label match — try keyword matching
            if "presence" in folder_lower:
                for project in projects:
                    if "presence" in project.get("label", "").lower():
                        return project

            if "maihera" in folder_lower:
                for project in projects:
                    if "maihera" in project.get("label", "").lower():
                        return project

        except Exception as e:
            logger.error(
                "FileWatcher: project match failed: %s", e
            )

        return None

    def _update_self_last_active(self) -> None:
        """Update last_active on self node to now."""
        try:
            with self._brain.driver.session() as session:
                session.run("""
                    MATCH (n:Node {type: 'self'})
                    SET n.last_active  = $now,
                        n.last_touched = $now
                """, now=datetime.utcnow().isoformat())
        except Exception as e:
            logger.error(
                "FileWatcher: self node update failed: %s", e
            )