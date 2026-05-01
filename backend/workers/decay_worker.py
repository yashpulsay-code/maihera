"""
MAIHERA Workers — Signal Decay Worker
Runs signal decay on all active brain nodes every hour.
Heartbeat keeps Neo4j Aura Free from pausing.
Weekly export runs every Sunday at 2AM local time.
Uses APScheduler with AsyncIOScheduler.
Starts automatically with FastAPI and stops cleanly on shutdown.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class DecayWorker:
    """
    Scheduled worker with three jobs:
    1. Signal decay — every hour on all active nodes
    2. Heartbeat — every 30 minutes, keeps Neo4j Aura alive
    3. Weekly export — every Sunday 2AM, JSON backup to backups/
    """

    def __init__(self, brain_service):
        self.brain = brain_service
        self.scheduler = AsyncIOScheduler()
        self._decay_count = 0
        self._heartbeat_count = 0
        self._export_count = 0
        self._last_decay: datetime | None = None
        self._last_heartbeat: datetime | None = None
        self._last_export: datetime | None = None
        self._error_count = 0

    def start(self) -> None:
        """Start all scheduled jobs."""

        # Job 1: Signal decay — every hour
        self.scheduler.add_job(
            func=self._run_decay,
            trigger=IntervalTrigger(hours=1),
            id='signal_decay',
            name='MAIHERA Signal Decay',
            replace_existing=True,
            misfire_grace_time=300
        )

        # Job 2: Heartbeat — every 30 minutes
        # Keeps Neo4j Aura Free from pausing during active sessions.
        # Aura pauses after 3 days of NO connections — the decay job
        # already touches Neo4j hourly, but the heartbeat adds an
        # explicit lightweight ping as a safety net.
        self.scheduler.add_job(
            func=self._run_heartbeat,
            trigger=IntervalTrigger(minutes=30),
            id='neo4j_heartbeat',
            name='MAIHERA Neo4j Heartbeat',
            replace_existing=True,
            misfire_grace_time=60
        )

        # Job 3: Weekly export — every Sunday at 2:00 AM local time
        self.scheduler.add_job(
            func=self._run_export,
            trigger=CronTrigger(
                day_of_week='sun',
                hour=2,
                minute=0
            ),
            id='weekly_export',
            name='MAIHERA Weekly Brain Export',
            replace_existing=True,
            misfire_grace_time=3600
        )

        self.scheduler.start()
        logger.info(
            "DecayWorker started — "
            "decay: hourly, heartbeat: 30min, export: Sunday 2AM."
        )

    def stop(self) -> None:
        """Stop the scheduler cleanly."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("DecayWorker stopped.")

    async def _run_decay(self) -> None:
        """
        Hourly decay job.
        Applies exponential decay to all active node signals.
        Logs node count and errors.
        """
        run_start = datetime.utcnow()
        logger.info("DecayWorker: running signal decay...")

        try:
            count = self.brain.apply_decay_all(hours_elapsed=1.0)
            self._decay_count += 1
            self._last_decay = run_start
            self._error_count = 0
            logger.info(
                "DecayWorker: %d nodes decayed (run #%d).",
                count, self._decay_count
            )

        except Exception as e:
            self._error_count += 1
            logger.error(
                "DecayWorker decay error "
                "(consecutive errors: %d): %s",
                self._error_count, e
            )
            if self._error_count >= 3:
                logger.critical(
                    "MAIHERA DecayWorker has failed %d times "
                    "consecutively. Brain signals are not decaying. "
                    "Check Neo4j connectivity.",
                    self._error_count
                )

    async def _run_heartbeat(self) -> None:
        """
        Heartbeat job — fires every 30 minutes.
        Sends a lightweight ping to Neo4j to prevent
        Aura Free from pausing the instance.
        If ping fails, logs a warning but does not crash.
        """
        try:
            with self.brain.driver.session() as session:
                result = session.run("RETURN 1 as alive")
                result.single()

            self._heartbeat_count += 1
            self._last_heartbeat = datetime.utcnow()
            logger.debug(
                "Neo4j heartbeat OK (ping #%d).",
                self._heartbeat_count
            )

        except Exception as e:
            logger.warning(
                "Neo4j heartbeat failed: %s. "
                "Instance may be pausing. "
                "Resume at console.neo4j.io if needed.",
                e
            )

    async def _run_export(self) -> None:
        """
        Weekly export job — fires every Sunday at 2AM.
        Dumps all nodes and edges to JSON in backups/ directory.
        Logs result to SQLite brain_export table.
        """
        logger.info("DecayWorker: running weekly brain export...")

        try:
            export_path = self.brain.export_to_json()
            self._export_count += 1
            self._last_export = datetime.utcnow()
            logger.info(
                "Weekly export complete: %s (export #%d).",
                export_path, self._export_count
            )

        except Exception as e:
            logger.error(
                "Weekly export failed: %s", e
            )
            # Log failed export to SQLite
            try:
                self.brain.db.log_export(
                    node_count=0,
                    edge_count=0,
                    export_path='',
                    status='failed'
                )
            except Exception:
                pass

    def get_stats(self) -> dict:
        """Return worker stats for health checks."""
        decay_job = self.scheduler.get_job('signal_decay')
        heartbeat_job = self.scheduler.get_job('neo4j_heartbeat')
        export_job = self.scheduler.get_job('weekly_export')

        return {
            'running': self.scheduler.running,
            'decay': {
                'total_runs': self._decay_count,
                'last_run': (
                    self._last_decay.isoformat()
                    if self._last_decay else None
                ),
                'next_run': (
                    str(decay_job.next_run_time)
                    if decay_job else None
                ),
                'consecutive_errors': self._error_count,
            },
            'heartbeat': {
                'total_pings': self._heartbeat_count,
                'last_ping': (
                    self._last_heartbeat.isoformat()
                    if self._last_heartbeat else None
                ),
                'next_ping': (
                    str(heartbeat_job.next_run_time)
                    if heartbeat_job else None
                ),
            },
            'export': {
                'total_exports': self._export_count,
                'last_export': (
                    self._last_export.isoformat()
                    if self._last_export else None
                ),
                'next_export': (
                    str(export_job.next_run_time)
                    if export_job else None
                ),
            }
        }


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from brain.brain_service import get_brain_service

    async def test_decay_worker():
        print("Testing MAIHERA DecayWorker (updated)...")

        brain, driver = get_brain_service()
        worker = DecayWorker(brain)

        try:
            # Test 1: Start scheduler
            print("\n[1] Starting scheduler...")
            worker.start()
            assert worker.scheduler.running
            print("    Scheduler running: OK")

            # Test 2: Run decay manually
            print("\n[2] Running decay...")
            await worker._run_decay()
            assert worker._decay_count == 1
            print(f"    Decay runs: {worker._decay_count} OK")

            # Test 3: Run heartbeat manually
            print("\n[3] Running heartbeat...")
            await worker._run_heartbeat()
            assert worker._heartbeat_count == 1
            print(f"    Heartbeat pings: {worker._heartbeat_count} OK")

            # Test 4: Run export manually
            print("\n[4] Running export...")
            await worker._run_export()
            assert worker._export_count == 1
            print(f"    Exports: {worker._export_count} OK")

            # Test 5: Check stats
            print("\n[5] Checking stats...")
            stats = worker.get_stats()
            print(f"    Running: {stats['running']}")
            print(f"    Decay runs: {stats['decay']['total_runs']}")
            print(
                f"    Heartbeat pings: "
                f"{stats['heartbeat']['total_pings']}"
            )
            print(
                f"    Export count: "
                f"{stats['export']['total_exports']}"
            )
            print(
                f"    Next export: "
                f"{stats['export']['next_export']}"
            )
            assert stats['running'] is True
            assert stats['decay']['total_runs'] == 1
            assert stats['heartbeat']['total_pings'] == 1
            assert stats['export']['total_exports'] == 1
            print("    Stats OK")

            # Test 6: Stop cleanly
            print("\n[6] Stopping scheduler...")
            worker.stop()
            print("    Stopped cleanly: OK")

            print("\n✅ DecayWorker test PASSED — all 6 checks OK")

        except Exception as e:
            print(f"\n❌ Test FAILED: {e}")
            raise
        finally:
            driver.close()

    asyncio.run(test_decay_worker())