"""
MAIHERA Calendar Worker
Background polling worker — syncs Google Calendar to brain every 15 minutes.
Skips sync during gym window (9:30-10:30 PM IST) and deep sleep (1-7 AM IST).
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SUPPRESSED_WINDOWS = [
    (21, 30, 22, 30),   # 9:30 PM – 10:30 PM — gym
    (1,  0,  7,  0),    # 1:00 AM – 7:00 AM  — sleep
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


class CalendarWorker:

    def __init__(self, calendar_service, brain_service):
        self._calendar_service = calendar_service
        self._brain_service    = brain_service
        self._scheduler        = BackgroundScheduler(timezone='UTC')
        self._sync_count       = 0
        self._last_sync        = None
        self._last_summary     = {}

    def _run_sync(self) -> None:
        """Scheduled sync job — runs in APScheduler background thread."""
        if _is_suppressed():
            logger.debug("CalendarWorker: suppressed window — skipping sync.")
            return

        async def _do_sync():
            try:
                summary = await self._calendar_service.sync_to_brain(
                    self._brain_service
                )
                self._sync_count += 1
                self._last_sync    = datetime.utcnow().isoformat()
                self._last_summary = summary

                total_changes = (
                    summary.get('created', 0) + summary.get('updated', 0)
                )
                if total_changes > 0:
                    logger.info(
                        "CalendarWorker: sync #%d — "
                        "created=%d updated=%d linked=%d unlinked=%d",
                        self._sync_count,
                        summary.get('created', 0),
                        summary.get('updated', 0),
                        summary.get('linked', 0),
                        summary.get('unlinked', 0),
                    )
                else:
                    logger.debug(
                        "CalendarWorker: sync #%d — no changes.",
                        self._sync_count
                    )
            except Exception as e:
                logger.error("CalendarWorker: sync failed — %s", e)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_do_sync())
        finally:
            loop.close()

    def start(self) -> None:
        """Start the polling scheduler. No immediate sync — uses date trigger."""
        # Recurring sync every 15 minutes
        self._scheduler.add_job(
            self._run_sync,
            trigger='interval',
            minutes=15,
            id='calendar_sync',
            replace_existing=True
        )
        # Initial sync 5 seconds after startup via date trigger
        # avoids asyncio event loop conflict during lifespan init
        self._scheduler.add_job(
            self._run_sync,
            trigger='date',
            run_date=datetime.utcnow() + timedelta(seconds=5),
            id='calendar_initial_sync',
            replace_existing=True
        )
        self._scheduler.start()
        logger.info("CalendarWorker: started — polling every 15 minutes.")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("CalendarWorker: stopped.")

    def get_stats(self) -> dict:
        return {
            'sync_count':    self._sync_count,
            'last_sync':     self._last_sync,
            'last_summary':  self._last_summary,
            'is_suppressed': _is_suppressed(),
        }