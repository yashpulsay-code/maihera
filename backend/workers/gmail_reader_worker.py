"""
MAIHERA Workers — Gmail Reader Worker
Polls MAIHERA's inbox every 5 minutes.
Surfaces high-importance emails immediately.
Queues medium emails for morning briefing.
Processes instruction emails from Yash as commands.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from services.gmail_reader_service import GmailReaderService
    from api.websocket_manager import WebSocketManager
    from services.voice_service import VoiceService

logger = logging.getLogger(__name__)


class GmailReaderWorker:
    """
    Polls Gmail every 5 minutes via APScheduler.
    On each poll:
        - Fetches new emails since last poll
        - Scores each email by importance tier
        - High → immediate voice + chat nudge
        - Medium → queued for morning briefing via nudge service
        - Instruction → processed as MAIHERA command
        - Low → logged to brain silently
    """

    def __init__(
        self,
        gmail_reader_service: "GmailReaderService",
    ):
        self.svc = gmail_reader_service
        self._ws_manager: "WebSocketManager | None" = None
        self._voice_service: "VoiceService | None" = None
        self._scheduler = AsyncIOScheduler()
        self._poll_count = 0

    def set_ws_manager(self, ws_manager: "WebSocketManager") -> None:
        self._ws_manager = ws_manager

    def set_voice_service(self, voice_service: "VoiceService") -> None:
        self._voice_service = voice_service

    def start(self) -> None:
        self._scheduler.add_job(
            self._run_poll,
            trigger="interval",
            minutes=5,
            id="gmail_reader_poll",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "GmailReaderWorker: started — polling every 5 minutes."
        )

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("GmailReaderWorker: stopped.")

    async def _run_poll(self) -> None:
        """Single poll cycle — called by scheduler."""
        self._poll_count += 1
        logger.info(
            "GmailReaderWorker: poll #%d", self._poll_count
        )

        try:
            summary = await self.svc.poll_inbox()

            if "error" in summary:
                logger.error(
                    "GmailReaderWorker: poll error — %s",
                    summary["error"]
                )
                return

            if summary["new"] == 0:
                return

            logger.info(
                "GmailReaderWorker: poll #%d — "
                "new=%d high=%d medium=%d instruction=%d low=%d",
                self._poll_count,
                summary["new"],
                summary.get("high", 0),
                summary.get("medium", 0),
                summary.get("instruction", 0),
                summary.get("low", 0),
            )

            # Surface high-importance emails immediately
            if summary.get("high", 0) > 0:
                await self._surface_high_emails()

            # Process instruction emails
            if summary.get("instruction", 0) > 0:
                await self._process_instructions()

        except Exception as e:
            logger.error(
                "GmailReaderWorker: unhandled error in poll: %s", e
            )

    async def _surface_high_emails(self) -> None:
        """
        Surface high-importance emails via voice and chat.
        Fetches the most recent high nodes from brain.
        """
        try:
            # Get recently created high-importance email nodes
            nodes = self.svc.brain.list_nodes(
                node_type="event", status="active"
            )
            # Filter to email nodes created in last 10 minutes
            from datetime import datetime, timedelta
            cutoff = (
                datetime.utcnow() - timedelta(minutes=10)
            ).isoformat()

            high_emails = [
                n for n in nodes
                if n.get("source") == "gmail"
                and n.get("importance", 0) >= 0.7
                and n.get("created_at", "") >= cutoff
            ]

            if not high_emails:
                return

            for node in high_emails[:3]:  # Max 3 at once
                subject = node["label"].replace("Email: ", "")
                desc_lines = node.get("description", "").split("\n")
                sender_line = desc_lines[0] if desc_lines else ""
                sender = sender_line.replace("From: ", "")

                msg = (
                    f"Boss, important email from {sender}: "
                    f"{subject}."
                )

                if self._voice_service:
                    await self._voice_service.enqueue_speech(
                        text=msg,
                        node_ids=[node["id"]],
                        priority="urgent",
                    )

                if self._ws_manager:
                    await self._ws_manager.send_maihera_speak(
                        text=msg,
                        node_ids=[node["id"]],
                        priority="urgent",
                    )

        except Exception as e:
            logger.error(
                "GmailReaderWorker: _surface_high_emails error: %s",
                e
            )

    async def _process_instructions(self) -> None:
        """
        Process emails from Yash as direct instructions.
        Fetches instruction-tier nodes created in last 10 minutes.
        """
        try:
            nodes = self.svc.brain.list_nodes(
                node_type="event", status="active"
            )
            from datetime import datetime, timedelta
            cutoff = (
                datetime.utcnow() - timedelta(minutes=10)
            ).isoformat()

            instruction_nodes = [
                n for n in nodes
                if n.get("source") == "gmail"
                and n.get("importance", 0) >= 0.85
                and n.get("created_at", "") >= cutoff
                and "yashpulsay" in n.get("description", "")
            ]

            for node in instruction_nodes:
                desc = node.get("description", "")
                lines = desc.split("\n")
                subject = ""
                snippet = ""
                for line in lines:
                    if line.startswith("Subject:"):
                        subject = line.replace("Subject:", "").strip()
                    elif line.startswith("Preview:"):
                        snippet = line.replace("Preview:", "").strip()

                parsed = {
                    "subject": subject,
                    "snippet": snippet,
                    "sender_email": "yashpulsay@gmail.com",
                    "tier": "instruction",
                }

                response = await self.svc.process_instruction_email(
                    parsed
                )
                if response and self._ws_manager:
                    msg = f"Boss, got your email instruction: {response}"
                    await self._ws_manager.send_maihera_speak(
                        text=msg,
                        node_ids=[node["id"]],
                        priority="normal",
                    )
                    if self._voice_service:
                        await self._voice_service.enqueue_speech(
                            text=msg,
                            node_ids=[node["id"]],
                            priority="normal",
                        )

        except Exception as e:
            logger.error(
                "GmailReaderWorker: _process_instructions error: %s",
                e
            )

    def get_stats(self) -> dict:
        return {"poll_count": self._poll_count}