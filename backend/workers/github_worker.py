"""
MAIHERA GitHub Worker
Polls Presence repo every 30 minutes for new commits.
Marks stale nodes. Queues re-analysis when logic files change.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

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
        self._github_service = github_service
        self._brain_service  = brain_service
        self._scheduler      = BackgroundScheduler(timezone='UTC')
        self._poll_count     = 0
        self._last_poll      = None
        self._last_summary   = {}

    def _run_poll(self) -> None:
        if _is_suppressed():
            logger.debug("GitHubWorker: suppressed window — skipping poll.")
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
                    if summary['needs_analysis']:
                        # Placeholder — full analysis built in B2b
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
                logger.error("GitHubWorker: poll failed — %s", e)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_do_poll())
        finally:
            loop.close()

    def start(self) -> None:
        self._scheduler.add_job(
            self._run_poll,
            trigger='interval',
            minutes=30,
            id='github_poll',
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "GitHubWorker: started — polling every 30 minutes."
        )
        self._run_poll()
        logger.info("GitHubWorker: initial poll complete.")

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