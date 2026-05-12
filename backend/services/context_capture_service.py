"""
MAIHERA Services — Context Capture
Zero-friction capture of ideas, tasks, and questions
from anywhere — commute, post-gym, mid-conversation.

Captured nodes enter 'staging' status, not 'active'.
Triage happens in Dream Mode or via morning briefing prompt.
Staged nodes expire after 7 days — never silently deleted,
always archived with a note.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brain.brain_service import BrainService
    from brain.sqlite_store import DatabaseManager
    from brain.classifier import NodeClassifier
    from llm.router import LLMRouter

logger = logging.getLogger(__name__)

# Days before a staged capture is auto-archived
STAGING_TTL_DAYS = 7


class ContextCaptureService:
    """
    Handles zero-friction capture of thoughts from any device.

    Flow:
        Yash speaks or types a thought.
        Classifier assigns type, project, signals.
        Node created in Neo4j with status='staging'.
        Staging record written to SQLite for triage tracking.
        Morning briefing surfaces count if > 0 staged.
        Dream Mode or manual triage promotes/merges/archives.
    """

    def __init__(
        self,
        brain_service: "BrainService",
        db: "DatabaseManager",
        classifier: "NodeClassifier",
        llm_router: "LLMRouter",
    ):
        self.brain = brain_service
        self.db = db
        self.classifier = classifier
        self.llm_router = llm_router
        self._ensure_staging_table()

    def _ensure_staging_table(self) -> None:
        """Create staging_captures table if it does not exist."""
        self.db.connection.execute("""
            CREATE TABLE IF NOT EXISTS staging_captures (
                id              TEXT PRIMARY KEY,
                node_id         TEXT NOT NULL,
                raw_text        TEXT NOT NULL,
                captured_at     TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                status          TEXT NOT NULL CHECK(status IN (
                                    'staged','promoted','merged',
                                    'archived','expired'
                                )),
                promoted_at     TEXT,
                merged_into     TEXT,
                archived_reason TEXT,
                triage_source   TEXT CHECK(triage_source IN (
                                    'dream','manual','auto', NULL
                                ))
            )
        """)
        self.db.connection.commit()
        logger.info("staging_captures table ready.")

    # ── Capture ───────────────────────────────────────────────────

    async def capture(
        self,
        raw_text: str,
        project_hint: Optional[str] = None,
        workspace: str = "personal",
    ) -> dict:
        """
        Capture a thought and stage it for triage.
        Returns the created node summary.

        This is the primary entry point — called from:
        - Voice input (Whisper transcription)
        - Chat message detected as capture intent
        - Mobile text input (Phase 5+)
        """
        if not raw_text or len(raw_text.strip()) < 3:
            return {"error": "Capture text too short."}

        # ── Classify ──────────────────────────────────────────────
        project_names = [
            p.get("label", "")
            for p in self.brain.list_nodes(node_type="project")
        ]
        if project_hint and project_hint not in project_names:
            project_names.append(project_hint)

        classification = await self.classifier.classify(
            raw_text, project_names
        )

        # ── Resolve project ID ────────────────────────────────────
        project_id = None
        hint = classification.get("project_id_hint") or project_hint
        if hint:
            for p in self.brain.list_nodes(node_type="project"):
                if hint.lower() in p.get("label", "").lower():
                    project_id = p["id"]
                    break

        # ── Create staged node ────────────────────────────────────
        node_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(days=STAGING_TTL_DAYS)

        node_data = {
            "id": node_id,
            "type": classification["type"],
            "label": classification["label"],
            "description": classification["description"],
            "project_id": project_id,
            "source": "manual",
            "importance": classification["importance_hint"],
            "attention": 0.6,
            "status": "staging",      # Not active — awaiting triage
            "visibility": "private",
            "workspace": workspace,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "created_at": now.isoformat(),
            "last_touched": now.isoformat(),
        }
        self.brain.create_node(node_data)

        # ── Write staging record ──────────────────────────────────
        capture_id = str(uuid.uuid4())
        self.db.connection.execute("""
            INSERT INTO staging_captures (
                id, node_id, raw_text, captured_at,
                expires_at, status
            ) VALUES (?, ?, ?, ?, ?, 'staged')
        """, (
            capture_id, node_id,
            raw_text.strip(),
            now.isoformat(),
            expires_at.isoformat(),
        ))
        self.db.connection.commit()

        logger.info(
            "Captured: '%s' → %s node (staging, expires %s)",
            raw_text[:50], classification["type"],
            expires_at.date().isoformat()
        )

        return {
            "capture_id": capture_id,
            "node_id": node_id,
            "type": classification["type"],
            "label": classification["label"],
            "project": hint,
            "expires_at": expires_at.isoformat(),
            "confirmation": (
                f"Got it Boss — staged as a "
                f"{classification['type']} under "
                f"{hint or 'no project'}. "
                f"I'll triage it tonight."
            ),
        }

    # ── Triage ────────────────────────────────────────────────────

    def get_staged_count(self) -> int:
        """Return count of staged captures awaiting triage."""
        cursor = self.db.connection.execute(
            "SELECT COUNT(*) FROM staging_captures WHERE status = 'staged'"
        )
        return cursor.fetchone()[0]

    def get_staged_captures(self, limit: int = 20) -> list[dict]:
        """Return staged captures ordered by captured_at ascending."""
        cursor = self.db.connection.execute("""
            SELECT * FROM staging_captures
            WHERE status = 'staged'
            ORDER BY captured_at ASC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def promote(self, capture_id: str) -> bool:
        """
        Promote a staged node to active status.
        Called by Dream Mode or manual triage.
        """
        capture = self._get_capture(capture_id)
        if not capture:
            logger.warning("promote: capture not found: %s", capture_id)
            return False

        # Activate the node in Neo4j
        try:
            self.brain.update_node_status(
                capture["node_id"], "active"
            )
        except Exception as e:
            logger.error("promote: Neo4j update failed: %s", e)
            return False

        # Update staging record
        now = datetime.utcnow().isoformat()
        self.db.connection.execute("""
            UPDATE staging_captures
            SET status = 'promoted', promoted_at = ?,
                triage_source = 'manual'
            WHERE id = ?
        """, (now, capture_id))
        self.db.connection.commit()
        logger.info("Promoted capture: %s → node %s", capture_id, capture["node_id"])
        return True

    def merge(self, capture_id: str, target_node_id: str) -> bool:
        """
        Merge a staged capture into an existing node.
        The staged node is archived; target node gets
        the capture's description appended.
        Called by Dream Mode when semantic similarity is high.
        """
        capture = self._get_capture(capture_id)
        if not capture:
            logger.warning("merge: capture not found: %s", capture_id)
            return False

        # Append raw text to target node description
        try:
            target = self.brain.get_node(target_node_id)
            if not target:
                logger.warning(
                    "merge: target node not found: %s", target_node_id
                )
                return False
            existing_desc = target.get("description", "")
            appended = (
                f"{existing_desc}\n\n"
                f"[Merged capture {datetime.utcnow().date()}]: "
                f"{capture['raw_text']}"
            ).strip()
            self.brain.update_node_description(target_node_id, appended)
        except Exception as e:
            logger.error("merge: brain update failed: %s", e)
            return False

        # Archive the staged node
        try:
            self.brain.update_node_status(
                capture["node_id"], "archived"
            )
        except Exception as e:
            logger.error("merge: archive staged node failed: %s", e)

        now = datetime.utcnow().isoformat()
        self.db.connection.execute("""
            UPDATE staging_captures
            SET status = 'merged', merged_into = ?,
                promoted_at = ?, triage_source = 'dream'
            WHERE id = ?
        """, (target_node_id, now, capture_id))
        self.db.connection.commit()
        logger.info(
            "Merged capture %s into node %s", capture_id, target_node_id
        )
        return True

    def archive(
        self,
        capture_id: str,
        reason: str = "Triage decision",
        triage_source: str = "manual",
    ) -> bool:
        """
        Archive a staged capture without promoting it.
        Node status set to archived — never deleted.
        """
        capture = self._get_capture(capture_id)
        if not capture:
            logger.warning("archive: capture not found: %s", capture_id)
            return False

        try:
            self.brain.update_node_status(
                capture["node_id"], "archived"
            )
        except Exception as e:
            logger.error("archive: Neo4j update failed: %s", e)
            return False

        now = datetime.utcnow().isoformat()
        self.db.connection.execute("""
            UPDATE staging_captures
            SET status = 'archived', promoted_at = ?,
                archived_reason = ?, triage_source = ?
            WHERE id = ?
        """, (now, reason, triage_source, capture_id))
        self.db.connection.commit()
        logger.info("Archived capture: %s (%s)", capture_id, reason)
        return True

    def expire_stale(self) -> int:
        """
        Archive staged captures past their TTL.
        Called by APScheduler daily.
        Returns count of expired captures.
        """
        now = datetime.utcnow().isoformat()
        cursor = self.db.connection.execute("""
            SELECT id, node_id FROM staging_captures
            WHERE status = 'staged' AND expires_at < ?
        """, (now,))
        stale = cursor.fetchall()

        count = 0
        for row in stale:
            capture_id, node_id = row[0], row[1]
            try:
                self.brain.update_node_status(node_id, "archived")
            except Exception as e:
                logger.error(
                    "expire_stale: node archive failed %s: %s",
                    node_id, e
                )

            self.db.connection.execute("""
                UPDATE staging_captures
                SET status = 'expired',
                    archived_reason = 'TTL expired after 7 days',
                    triage_source = 'auto'
                WHERE id = ?
            """, (capture_id,))
            count += 1

        if count:
            self.db.connection.commit()
            logger.info("Expired %d stale captures.", count)

        return count

    def get_triage_briefing_text(self) -> Optional[str]:
        """
        Returns a briefing line for morning briefing if
        staged captures are waiting. None if none waiting.
        """
        count = self.get_staged_count()
        if count == 0:
            return None
        if count == 1:
            return (
                "Boss, you have 1 staged capture waiting for triage. "
                "Want to handle it now or leave it for tonight?"
            )
        return (
            f"Boss, you have {count} staged captures waiting. "
            f"Want to triage them now or leave them for tonight?"
        )

    # ── Internal ──────────────────────────────────────────────────

    def _get_capture(self, capture_id: str) -> Optional[dict]:
        cursor = self.db.connection.execute(
            "SELECT * FROM staging_captures WHERE id = ?",
            (capture_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None