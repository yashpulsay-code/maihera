"""
MAIHERA Services — Gmail Reader
Reads MAIHERA's inbox (maihera.ai@gmail.com).
Scores emails by urgency. Surfaces important ones via nudge.
Treats direct emails from Yash as instructions.

Polling: every 5 minutes via GmailReaderWorker.
Storage: message IDs tracked in SQLite gmail_read_state table.
Brain: important emails become event nodes. Senders become person nodes.
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brain.brain_service import BrainService
    from llm.router import LLMRouter

logger = logging.getLogger(__name__)

# ── Importance Rules ──────────────────────────────────────────────
# Sender domain → base importance tier
# LLM refines within tier based on subject + snippet

SENDER_RULES: dict[str, str] = {
    "github.com":         "high",
    "noreply@github.com": "high",
    "anthropic.com":      "high",
    "groq.com":           "high",
    "ai.google.dev":      "high",
    "google.com":         "medium",
    "cartesia.ai":        "high",
    "elevenlabs.io":      "high",
    "openai.com":         "high",
    "openrouter.ai":      "medium",
    "yashpulsay@gmail.com": "instruction",
    # instruction = direct command from Yash — always processed
}

# GitHub subjects that are always high urgency
GITHUB_HIGH_PATTERNS = [
    "security alert",
    "secret scanning",
    "vulnerability",
    "failing",
    "failed",
    "review requested",
    "mentioned you",
    "assigned",
]

# GitHub subjects that are medium (bot noise)
GITHUB_MEDIUM_PATTERNS = [
    "dependabot",
    "bot",
    "renovate",
    "closed",
    "merged",
]

MAIHERA_ACCOUNT = "maihera.ai@gmail.com"
YASH_EMAIL = "yashpulsay@gmail.com"


class GmailReaderService:
    """
    Reads MAIHERA's Gmail inbox and scores incoming emails.

    Importance tiers:
        high        — surface immediately via voice + chat nudge
        medium      — surface in next morning briefing
        low         — log to graph silently, no interrupt
        instruction — email from Yash to MAIHERA — process as command
    """

    def __init__(
        self,
        brain_service: "BrainService",
        llm_router: "LLMRouter",
    ):
        self.brain = brain_service
        self.llm_router = llm_router
        self._service = None   # Gmail API client, built on first use

    def _get_service(self):
        """Build and cache the Gmail API client."""
        if self._service:
            return self._service
        from services.google_auth_service import GoogleAuthService
        from googleapiclient.discovery import build
        auth = GoogleAuthService()
        creds = auth.get_credentials()
        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ── Polling ───────────────────────────────────────────────────

    async def poll_inbox(self) -> dict:
        """
        Fetch new emails since last poll.
        Returns summary of what was found and surfaced.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._poll_sync)

    def _poll_sync(self) -> dict:
        """Synchronous poll — runs in executor."""
        try:
            service = self._get_service()
            last_ts = self._get_last_poll_timestamp()
            query = f"after:{last_ts} in:inbox"

            result = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=20,
            ).execute()

            messages = result.get("messages", [])
            if not messages:
                logger.info("GmailReader: no new messages.")
                self._set_last_poll_timestamp()
                return {"new": 0, "high": 0, "medium": 0,
                        "instruction": 0, "low": 0}

            summary = {"new": 0, "high": 0, "medium": 0,
                       "instruction": 0, "low": 0}

            for msg_ref in messages:
                msg_id = msg_ref["id"]
                if self._already_processed(msg_id):
                    continue

                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()

                parsed = self._parse_message(msg)
                if not parsed:
                    self._mark_processed(msg_id, "low")
                    continue

                tier = self._score_email(parsed)
                parsed["tier"] = tier
                summary["new"] += 1
                summary[tier] = summary.get(tier, 0) + 1

                self._create_brain_node(parsed)
                self._mark_processed(msg_id, tier)

                logger.info(
                    "GmailReader: [%s] %s — %s",
                    tier.upper(),
                    parsed["sender_email"],
                    parsed["subject"][:60],
                )

            self._set_last_poll_timestamp()
            return summary

        except Exception as e:
            logger.error("GmailReader poll error: %s", e)
            return {"error": str(e)}

    # ── Parsing ───────────────────────────────────────────────────

    def _parse_message(self, msg: dict) -> Optional[dict]:
        """Extract sender, subject, snippet from Gmail API response."""
        try:
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            raw_from = headers.get("From", "")
            subject = headers.get("Subject", "(no subject)")
            snippet = msg.get("snippet", "")
            date_str = headers.get("Date", "")

            # Extract email address from "Name <email>" format
            match = re.search(r'<(.+?)>', raw_from)
            sender_email = match.group(1) if match else raw_from
            sender_name = raw_from.split("<")[0].strip().strip('"')

            return {
                "message_id": msg["id"],
                "sender_email": sender_email.lower(),
                "sender_name": sender_name,
                "subject": subject,
                "snippet": snippet[:300],
                "date_str": date_str,
            }
        except Exception as e:
            logger.error("GmailReader parse error: %s", e)
            return None

    # ── Scoring ───────────────────────────────────────────────────

    def _score_email(self, parsed: dict) -> str:
        """
        Score email importance tier.
        Returns: high | medium | low | instruction
        """
        sender = parsed["sender_email"]
        subject = parsed["subject"].lower()

        # Direct instruction from Yash — always process
        if sender == YASH_EMAIL:
            return "instruction"

        # Find matching sender rule
        base_tier = "low"
        for domain, tier in SENDER_RULES.items():
            if domain in sender:
                base_tier = tier
                break

        if base_tier == "low":
            return "low"

        # Refine GitHub emails by subject pattern
        if "github.com" in sender or "github" in sender:
            for pattern in GITHUB_HIGH_PATTERNS:
                if pattern in subject:
                    return "high"
            for pattern in GITHUB_MEDIUM_PATTERNS:
                if pattern in subject:
                    return "medium"
            return "medium"   # GitHub default = medium

        return base_tier

    # ── Brain Integration ─────────────────────────────────────────

    def _create_brain_node(self, parsed: dict) -> None:
        """
        Create an event node for important emails.
        Low-tier emails are not added to the graph.
        """
        if parsed["tier"] == "low":
            return

        import uuid
        node_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        importance = {
            "high": 0.8,
            "medium": 0.5,
            "instruction": 0.9,
        }.get(parsed["tier"], 0.3)

        attention = {
            "high": 0.9,
            "medium": 0.6,
            "instruction": 1.0,
        }.get(parsed["tier"], 0.2)

        label = f"Email: {parsed['subject'][:60]}"
        description = (
            f"From: {parsed['sender_name']} <{parsed['sender_email']}>\n"
            f"Subject: {parsed['subject']}\n"
            f"Preview: {parsed['snippet']}"
        )

        node_data = {
            "id": node_id,
            "type": "event",
            "label": label,
            "description": description,
            "project_id": None,
            "source": "gmail",
            "importance": importance,
            "attention": attention,
            "status": "active",
            "visibility": "private",
            "workspace": "personal",
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "source_ref": f"gmail:{parsed['message_id']}",
            "created_at": now,
            "last_touched": now,
        }

        try:
            self.brain.create_node(node_data)
            self._ensure_person_node(parsed)
            logger.debug(
                "Brain node created for email: %s", label
            )
        except Exception as e:
            logger.error(
                "GmailReader: brain node creation failed: %s", e
            )

    def _ensure_person_node(self, parsed: dict) -> None:
        """
        Create or update a person node for the sender.
        Skips GitHub bot addresses.
        """
        sender = parsed["sender_email"]
        if "noreply" in sender or "bot" in sender:
            return

        existing = self.brain.find_node_by_source_ref(
            f"person:{sender}"
        )
        if existing:
            self.brain.update_node(
                existing["id"],
                {"last_touched": datetime.utcnow().isoformat()}
            )
            return

        import uuid
        person_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        self.brain.create_node({
            "id": person_id,
            "type": "person",
            "label": parsed["sender_name"] or sender,
            "description": f"Contact: {sender}",
            "project_id": None,
            "source": "gmail",
            "importance": 0.5,
            "attention": 0.4,
            "status": "active",
            "visibility": "private",
            "workspace": "personal",
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "source_ref": f"person:{sender}",
            "created_at": now,
            "last_touched": now,
        })

    # ── Instruction Processing ────────────────────────────────────

    async def process_instruction_email(
        self, parsed: dict
    ) -> Optional[str]:
        """
        Process an email from Yash as a direct instruction.
        Routes the subject + snippet to the LLM as a chat message.
        Returns MAIHERA's response text.
        """
        instruction_text = (
            f"{parsed['subject']}. {parsed['snippet']}"
        ).strip()

        logger.info(
            "Processing instruction email: %s", instruction_text[:80]
        )

        try:
            from llm.persona import build_system_prompt
            projects = self.brain.list_nodes(node_type="project")
            active_projects = [
                p for p in projects if p.get("status") == "active"
            ]
            system_prompt = build_system_prompt(
                self_node=None,
                active_projects=active_projects,
                high_signal_nodes=[],
            )
            response = await self.llm_router.route(
                task_type="conversation",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Yash sent this instruction via email: "
                        f"{instruction_text}"
                    )
                }],
                system_prompt=system_prompt,
                max_tokens=400,
            )
            return response
        except Exception as e:
            logger.error(
                "Instruction email processing failed: %s", e
            )
            return None

    # ── SQLite State ──────────────────────────────────────────────

    def _already_processed(self, message_id: str) -> bool:
        cursor = self.brain.db.connection.execute(
            "SELECT 1 FROM gmail_read_state WHERE key = ?",
            (f"msg:{message_id}",)
        )
        return cursor.fetchone() is not None

    def _mark_processed(self, message_id: str, tier: str) -> None:
        self.brain.db.connection.execute("""
            INSERT INTO gmail_read_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING
        """, (f"msg:{message_id}", tier))
        self.brain.db.connection.commit()

    def _get_last_poll_timestamp(self) -> int:
        """Returns Unix timestamp of last poll for Gmail query."""
        cursor = self.brain.db.connection.execute(
            "SELECT value FROM gmail_read_state WHERE key = ?",
            ("gmail_reader_last_poll",)
        )
        row = cursor.fetchone()
        if row:
            return int(row[0])
        # Default: last 24 hours on first run
        import time
        return int(time.time()) - 86400

    def _set_last_poll_timestamp(self) -> None:
        import time
        ts = str(int(time.time()))
        self.brain.db.connection.execute("""
            INSERT INTO gmail_read_state (key, value)
            VALUES ('gmail_reader_last_poll', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (ts,))
        self.brain.db.connection.commit()

    # ── SQLite Table Init ─────────────────────────────────────────

    def ensure_read_state_table(self) -> None:
        """Create gmail_read_state table if it does not exist."""
        self.brain.db.connection.execute("""
            CREATE TABLE IF NOT EXISTS gmail_read_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.brain.db.connection.commit()
        logger.info("gmail_read_state table ready.")