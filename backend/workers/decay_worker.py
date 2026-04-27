"""
MAIHERA Workers — Signal Decay Worker
Runs signal decay on all active brain nodes every hour.
Uses APScheduler with AsyncIOScheduler.
Starts automatically with FastAPI and stops cleanly on shutdown.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class DecayWorker:
    """
    Scheduled worker that applies exponential signal decay
    to all active nodes in the brain graph every hour.
    Integrated into FastAPI lifespan — not a separate process.
    """

    def __init__(self, brain_service):
        self.brain = brain_service
        self.scheduler = AsyncIOScheduler()
        self._decay_count = 0
        self._last_run: datetime | None = None
        self._error_count = 0

    def start(self) -> None:
        """Start the decay scheduler."""
        self.scheduler.add_job(
            func=self._run_decay,
            trigger=IntervalTrigger(hours=1),
            id='signal_decay',
            name='MAIHERA Signal Decay',
            replace_existing=True,
            misfire_grace_time=300
        )
        self.scheduler.start()
        logger.info("DecayWorker started — firing every 60 minutes.")

    def stop(self) -> None:
        """Stop the scheduler cleanly."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("DecayWorker stopped.")

    async def _run_decay(self) -> None:
        """
        The scheduled decay job.
        Calls brain_service.apply_decay_all with 1 hour elapsed.
        Logs node count decayed and any errors.
        Updates internal stats.
        """
        run_start = datetime.utcnow()
        logger.info("DecayWorker firing — applying signal decay...")

        try:
            count = self.brain.apply_decay_all(hours_elapsed=1.0)
            self._decay_count += 1
            self._last_run = run_start
            self._error_count = 0
            logger.info(
                "DecayWorker complete — %d nodes decayed "
                "(run #%d at %s)",
                count, self._decay_count,
                run_start.strftime('%H:%M:%S')
            )

        except Exception as e:
            self._error_count += 1
            logger.error(
                "DecayWorker error (consecutive errors: %d): %s",
                self._error_count, e
            )
            # Surface alert if errors are accumulating
            if self._error_count >= 3:
                logger.critical(
                    "MAIHERA DecayWorker has failed %d times "
                    "consecutively. Brain signals are not decaying. "
                    "Check Neo4j connectivity.",
                    self._error_count
                )

    def get_stats(self) -> dict:
        """Return worker stats for health checks."""
        return {
            'running': self.scheduler.running,
            'total_decay_runs': self._decay_count,
            'last_run': (
                self._last_run.isoformat()
                if self._last_run else None
            ),
            'consecutive_errors': self._error_count,
            'next_run': (
                str(self.scheduler.get_job('signal_decay').next_run_time)
                if self.scheduler.get_job('signal_decay') else None
            )
        }


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from brain.brain_service import get_brain_service

    async def test_decay_worker():
        print("Testing MAIHERA DecayWorker...")

        brain, driver = get_brain_service()
        worker = DecayWorker(brain)

        try:
            # Test 1: Start the scheduler
            print("\n[1] Starting scheduler...")
            worker.start()
            assert worker.scheduler.running
            print("    Scheduler running: OK")

            # Test 2: Fire decay manually
            print("\n[2] Running decay manually...")
            await worker._run_decay()
            print(f"    Decay runs: {worker._decay_count}")
            assert worker._decay_count == 1

            # Test 3: Check stats
            print("\n[3] Checking stats...")
            stats = worker.get_stats()
            print(f"    Stats: {stats}")
            assert stats['running'] is True
            assert stats['total_decay_runs'] == 1
            assert stats['last_run'] is not None
            print("    Stats OK")

            # Test 4: Stop cleanly
            print("\n[4] Stopping scheduler...")
            worker.stop()
            print("    Stopped cleanly: OK")

            print("\n✅ DecayWorker test PASSED — all 4 checks OK")

        except Exception as e:
            print(f"\n❌ Test FAILED: {e}")
            raise
        finally:
            driver.close()

    asyncio.run(test_decay_worker())