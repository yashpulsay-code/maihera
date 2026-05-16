"""
MAIHERA GitHub Worker
Polls Presence repo every 30 minutes for new commits.
Marks stale nodes. Queues re-analysis when logic files change.
Triggers PresenceHealthWorker smoke test on new Presence pushes.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SUPPRESSED_WINDOWS = [
    (21, 30, 22, 30),   # gym
    (1,  0,  7,  0),    # sleep
]


def _is_suppressed() -> bool:
    now_ist = datetime.now(IST)
    current_minutes = now_ist.hour * 60 + now_ist.minute
    for start_h, start_m, end_h, end_m in SUPPRESSED_WINDOWS:
        start = start_h * 60 + start_m
        end   = end_h   * 60 + end_m
        if start <= current_minutes < end:
            return True
    return False


class GitHubWorker:

    def __init__(self, github_service, brain_service):
        self._github_service     = github_service
        self._brain_service      = brain_service
        self._scheduler          = BackgroundScheduler(timezone='UTC')
        self._poll_count         = 0
        self._last_poll          = None
        self._last_summary       = {}

        # Health worker — wired in after instantiation
        self._health_worker      = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_health_worker(
        self,
        health_worker,
        main_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Wire in the PresenceHealthWorker and the main event loop.
        Must be called before start().
        main_loop is the FastAPI asyncio event loop — required to
        schedule health checks as coroutine tasks from this thread.
        """
        self._health_worker = health_worker
        self._main_loop     = main_loop
        logger.info("GitHubWorker: PresenceHealthWorker wired.")

    def _run_poll(self) -> None:
        """Scheduled poll job — runs in APScheduler background thread."""
        if _is_suppressed():
            logger.debug(
                "GitHubWorker: suppressed window — skipping poll."
            )
            return

        async def _do_poll():
            try:
                summary = await self._github_service.check_new_commits(
                    self._brain_service
                )
                self._poll_count  += 1
                self._last_poll    = datetime.utcnow().isoformat()
                self._last_summary = summary

                if summary['new_commits'] > 0:
                    logger.info(
                        "GitHubWorker: poll #%d — "
                        "%d new commit(s), %d stale node(s), "
                        "needs_analysis=%s",
                        self._poll_count,
                        summary['new_commits'],
                        summary['stale_nodes'],
                        summary['needs_analysis'],
                    )

                    # Trigger health check if Presence push detected
                    self._maybe_trigger_health_check(summary)

                    if summary['needs_analysis']:
                        logger.info(
                            "GitHubWorker: re-analysis queued "
                            "for Presence codebase changes."
                        )
                else:
                    logger.debug(
                        "GitHubWorker: poll #%d — no new commits.",
                        self._poll_count
                    )

            except Exception as e:
                import traceback
                logger.error(
                    "GitHubWorker: poll failed — %s\n%s",
                    e, traceback.format_exc()
                )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_do_poll())
        finally:
            loop.close()

    def _maybe_trigger_health_check(self, summary: dict) -> None:
        """
        If new commits were detected and the health worker is wired,
        schedule a smoke test on the main FastAPI event loop.
        Thread-safe bridge from APScheduler thread → asyncio loop.
        """
        if not self._health_worker or not self._main_loop:
            return

        # Extract most recent commit info from summary
        # GitHubService returns latest_sha and latest_message
        # in the summary dict — use them if present
        commit_sha     = summary.get("latest_sha", "unknown")
        commit_message = summary.get("latest_message", "")

        if commit_sha == "unknown":
            logger.debug(
                "GitHubWorker: no SHA in summary — "
                "skipping health check trigger."
            )
            return

        logger.info(
            "GitHubWorker: triggering Presence health check "
            "for push %s.", commit_sha[:8]
        )

        # Schedule the coroutine on the main event loop
        # from this background thread
        asyncio.run_coroutine_threadsafe(
            self._health_worker.on_presence_push(
                commit_sha=commit_sha,
                commit_message=commit_message,
            ),
            self._main_loop,
        )

    def start(self) -> None:
        """Start the polling scheduler."""
        self._scheduler.add_job(
            self._run_poll,
            trigger='interval',
            minutes=30,
            id='github_poll',
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._run_poll,
            trigger='date',
            run_date=datetime.utcnow() + timedelta(seconds=10),
            id='github_initial_poll',
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "GitHubWorker: started — polling every 30 minutes."
        )

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("GitHubWorker: stopped.")

    def get_stats(self) -> dict:
        return {
            'poll_count':    self._poll_count,
            'last_poll':     self._last_poll,
            'last_summary':  self._last_summary,
            'is_suppressed': _is_suppressed(),
        }