"""
MAIHERA Brain Layer — SQLite Operational Database
Manages task state, decision log, signal decay audit,
session tracking, focus sessions, briefing log,
and brain export/backup.
"""

import os
import sqlite3
import uuid
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Single interface for all SQLite operations.
    Manages task state, decision log, decay audit,
    session log, focus sessions, briefing log,
    and brain export.
    """

    def __init__(self, db_path: Optional[str] = None):
        raw = db_path or os.getenv('SQLITE_DB_PATH', './maihera.db')
        self.db_path = Path(__file__).parent.parent / raw
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Open the SQLite connection."""
        self.connection = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        logger.info(f"SQLite connected: {self.db_path}")

    def disconnect(self) -> None:
        """Close the SQLite connection cleanly."""
        if hasattr(self, 'connection') and self.connection:
            self.connection.close()
            logger.info("SQLite connection closed.")

    def initialize(self) -> None:
        """Create all tables if they do not exist."""
        self.connect()
        self._create_task_state_table()
        self._create_decision_log_table()
        self._create_signal_decay_log_table()
        self._create_session_log_table()
        self._create_brain_export_table()
        self._create_focus_sessions_table()
        self._create_briefing_log_table()
        self._create_github_state_table()
        self._create_orchestrator_tasks_table()
        self._create_confirmations_table()
        self.connection.commit()
        logger.info("All SQLite tables initialized.")

    # ── Table Creation ─────────────────────────────────────────────

    def _create_task_state_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS task_state (
                id          TEXT PRIMARY KEY,
                node_id     TEXT NOT NULL,
                status      TEXT NOT NULL CHECK(status IN (
                                'pending','running','paused',
                                'completed','failed','cancelled'
                            )),
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                context     TEXT,
                retry_count INTEGER DEFAULT 0,
                error       TEXT
            )
        """)

    def _create_decision_log_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS decision_log (
                id                    TEXT PRIMARY KEY,
                node_id               TEXT NOT NULL,
                decision_type         TEXT NOT NULL,
                signals_snapshot      TEXT NOT NULL,
                chosen_action         TEXT NOT NULL,
                alternatives_considered TEXT,
                reasoning             TEXT,
                created_at            TEXT NOT NULL
            )
        """)

    def _create_signal_decay_log_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS signal_decay_log (
                id           TEXT PRIMARY KEY,
                node_id      TEXT NOT NULL,
                signal_name  TEXT NOT NULL,
                value_before REAL NOT NULL,
                value_after  REAL NOT NULL,
                decayed_at   TEXT NOT NULL
            )
        """)

    def _create_session_log_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                id           TEXT PRIMARY KEY,
                started_at   TEXT NOT NULL,
                last_active  TEXT NOT NULL,
                session_type TEXT NOT NULL CHECK(session_type IN (
                                 'active','dream','idle'
                             ))
            )
        """)

    def _create_brain_export_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS brain_export (
                id          TEXT PRIMARY KEY,
                exported_at TEXT NOT NULL,
                node_count  INTEGER NOT NULL,
                edge_count  INTEGER NOT NULL,
                export_path TEXT NOT NULL,
                status      TEXT NOT NULL CHECK(status IN (
                                'success','failed'
                            ))
            )
        """)

    def _create_focus_sessions_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id               TEXT PRIMARY KEY,
                started_at       TEXT NOT NULL,
                ended_at         TEXT,
                duration_minutes INTEGER,
                energy_at_start  INTEGER,
                pending_nudges   TEXT NOT NULL DEFAULT '[]',
                delivered_at     TEXT
            )
        """)

    def _create_briefing_log_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS briefing_log (
                id           TEXT PRIMARY KEY,
                delivered_at TEXT NOT NULL,
                date_key     TEXT NOT NULL,
                segment_count INTEGER NOT NULL DEFAULT 0,
                completed    INTEGER NOT NULL DEFAULT 0
            )
        """)

    def _create_github_state_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS github_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

    def _create_orchestrator_tasks_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_tasks (
                id                  TEXT PRIMARY KEY,
                action_type         TEXT NOT NULL,
                tool_name           TEXT NOT NULL,
                payload             TEXT NOT NULL,
                status              TEXT NOT NULL CHECK(status IN (
                                        'pending_confirmation','queued','running',
                                        'paused','completed','failed',
                                        'cancelled','expired'
                                    )),
                requires_confirmation INTEGER NOT NULL DEFAULT 0,
                confirmation_id     TEXT,
                autonomy_tier       TEXT NOT NULL CHECK(autonomy_tier IN (
                                        'always_allow','confirm_first',
                                        'always_confirm','explicit_only'
                                    )),
                created_at          TEXT NOT NULL,
                started_at          TEXT,
                completed_at        TEXT,
                retry_count         INTEGER NOT NULL DEFAULT 0,
                max_retries         INTEGER NOT NULL DEFAULT 3,
                last_error          TEXT,
                result              TEXT,
                verified            INTEGER NOT NULL DEFAULT 0,
                verification_result TEXT,
                parent_skill_id     TEXT,
                skill_step_index    INTEGER,
                FOREIGN KEY (confirmation_id)
                    REFERENCES confirmations(id)
            )
        """)

    def _create_confirmations_table(self) -> None:
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS confirmations (
                id              TEXT PRIMARY KEY,
                task_id         TEXT NOT NULL,
                action_summary  TEXT NOT NULL,
                full_detail     TEXT NOT NULL,
                status          TEXT NOT NULL CHECK(status IN (
                                    'pending','confirmed',
                                    'cancelled','expired','superseded'
                                )),
                created_at      TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                resolved_at     TEXT,
                resolved_by     TEXT CHECK(resolved_by IN (
                                    'voice','text','auto','timeout', NULL
                                ))
            )
        """)

    # ── Task State CRUD ────────────────────────────────────────────

    def create_task(
        self,
        node_id: str,
        context: Optional[dict] = None
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            INSERT INTO task_state
                (id, node_id, status, created_at, updated_at, context)
            VALUES (?, ?, 'pending', ?, ?, ?)
        """, (
            task_id, node_id, now, now,
            json.dumps(context or {})
        ))
        self.connection.commit()
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        cursor = self.connection.execute(
            "SELECT * FROM task_state WHERE id = ?", (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_task_status(
        self,
        task_id: str,
        status: str,
        error: Optional[str] = None
    ) -> None:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            UPDATE task_state
            SET status = ?, updated_at = ?, error = ?
            WHERE id = ?
        """, (status, now, error, task_id))
        self.connection.commit()

    def increment_retry(self, task_id: str) -> None:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            UPDATE task_state
            SET retry_count = retry_count + 1, updated_at = ?
            WHERE id = ?
        """, (now, task_id))
        self.connection.commit()

    def list_tasks(
        self,
        status: Optional[str] = None,
        node_id: Optional[str] = None
    ) -> list[dict]:
        query = "SELECT * FROM task_state WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if node_id:
            query += " AND node_id = ?"
            params.append(node_id)
        query += " ORDER BY created_at DESC"
        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # ── Decision Log CRUD ─────────────────────────────────────────

    def log_decision(
        self,
        node_id: str,
        decision_type: str,
        signals_snapshot: dict,
        chosen_action: str,
        alternatives: Optional[list] = None,
        reasoning: Optional[str] = None
    ) -> str:
        decision_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            INSERT INTO decision_log (
                id, node_id, decision_type, signals_snapshot,
                chosen_action, alternatives_considered,
                reasoning, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_id, node_id, decision_type,
            json.dumps(signals_snapshot), chosen_action,
            json.dumps(alternatives or []),
            reasoning, now
        ))
        self.connection.commit()
        return decision_id

    def get_decisions_for_node(self, node_id: str) -> list[dict]:
        cursor = self.connection.execute("""
            SELECT * FROM decision_log
            WHERE node_id = ?
            ORDER BY created_at DESC
        """, (node_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_decisions(self, limit: int = 20) -> list[dict]:
        cursor = self.connection.execute("""
            SELECT * FROM decision_log
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    # ── Signal Decay Log ──────────────────────────────────────────

    def log_decay(
        self,
        node_id: str,
        signal_name: str,
        value_before: float,
        value_after: float
    ) -> None:
        self.connection.execute("""
            INSERT INTO signal_decay_log
                (id, node_id, signal_name,
                 value_before, value_after, decayed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()), node_id, signal_name,
            value_before, value_after,
            datetime.utcnow().isoformat()
        ))
        self.connection.commit()

    def get_decay_history(
        self,
        node_id: str,
        signal_name: Optional[str] = None
    ) -> list[dict]:
        query = """
            SELECT * FROM signal_decay_log
            WHERE node_id = ?
        """
        params = [node_id]
        if signal_name:
            query += " AND signal_name = ?"
            params.append(signal_name)
        query += " ORDER BY decayed_at DESC LIMIT 100"
        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # ── Session Log ───────────────────────────────────────────────

    def start_session(
        self,
        session_type: str = 'active'
    ) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            INSERT INTO session_log
                (id, started_at, last_active, session_type)
            VALUES (?, ?, ?, ?)
        """, (session_id, now, now, session_type))
        self.connection.commit()
        return session_id

    def update_session_activity(self, session_id: str) -> None:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            UPDATE session_log
            SET last_active = ?
            WHERE id = ?
        """, (now, session_id))
        self.connection.commit()

    def get_last_session(self) -> Optional[dict]:
        cursor = self.connection.execute("""
            SELECT * FROM session_log
            ORDER BY started_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Brain Export Log ──────────────────────────────────────────

    def log_export(
        self,
        node_count: int,
        edge_count: int,
        export_path: str,
        status: str = 'success'
    ) -> str:
        export_id = str(uuid.uuid4())
        self.connection.execute("""
            INSERT INTO brain_export
                (id, exported_at, node_count,
                 edge_count, export_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            export_id,
            datetime.utcnow().isoformat(),
            node_count, edge_count,
            export_path, status
        ))
        self.connection.commit()
        return export_id

    def get_last_export(self) -> Optional[dict]:
        cursor = self.connection.execute("""
            SELECT * FROM brain_export
            ORDER BY exported_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Focus Sessions ────────────────────────────────────────────

    def start_focus_session(
        self,
        session_id: str,
        energy_level: Optional[int] = None
    ) -> None:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            INSERT INTO focus_sessions
                (id, started_at, energy_at_start, pending_nudges)
            VALUES (?, ?, ?, '[]')
        """, (session_id, now, energy_level))
        self.connection.commit()
        logger.info(f"Focus session started: {session_id}")

    def append_nudge_to_session(
        self,
        session_id: str,
        nudge: dict
    ) -> None:
        cursor = self.connection.execute(
            "SELECT pending_nudges FROM focus_sessions WHERE id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Focus session not found: {session_id}")
            return
        nudges = json.loads(row[0])
        nudges.append(nudge)
        self.connection.execute("""
            UPDATE focus_sessions
            SET pending_nudges = ?
            WHERE id = ?
        """, (json.dumps(nudges), session_id))
        self.connection.commit()

    def end_focus_session(
        self,
        session_id: str
    ) -> list[dict]:
        """
        Close the focus session. Returns pending nudges sorted
        by priority (urgent first) for end-of-session delivery.
        """
        now = datetime.utcnow().isoformat()
        cursor = self.connection.execute(
            "SELECT started_at, pending_nudges FROM focus_sessions WHERE id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Focus session not found: {session_id}")
            return []

        started_at = datetime.fromisoformat(row[0])
        ended_at = datetime.utcnow()
        duration = int((ended_at - started_at).total_seconds() / 60)
        nudges = json.loads(row[1])

        self.connection.execute("""
            UPDATE focus_sessions
            SET ended_at = ?, duration_minutes = ?, delivered_at = ?
            WHERE id = ?
        """, (now, duration, now, session_id))
        self.connection.commit()

        priority_order = {'urgent': 0, 'normal': 1}
        nudges.sort(key=lambda n: priority_order.get(n.get('priority', 'normal'), 1))
        logger.info(f"Focus session ended: {session_id}, duration: {duration}m, nudges: {len(nudges)}")
        return nudges

    def get_active_focus_session(self) -> Optional[dict]:
        """Return the currently open focus session, if any."""
        cursor = self.connection.execute("""
            SELECT * FROM focus_sessions
            WHERE ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Briefing Log ──────────────────────────────────────────────

    def log_briefing_delivered(
        self,
        segment_count: int = 0,
        completed: bool = True
    ) -> str:
        briefing_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        date_key = date.today().isoformat()
        self.connection.execute("""
            INSERT INTO briefing_log
                (id, delivered_at, date_key, segment_count, completed)
            VALUES (?, ?, ?, ?, ?)
        """, (briefing_id, now, date_key, segment_count, int(completed)))
        self.connection.commit()
        return briefing_id

    def briefing_delivered_today(self) -> bool:
        """Returns True if a completed briefing was delivered today."""
        date_key = date.today().isoformat()
        cursor = self.connection.execute("""
            SELECT COUNT(*) as count FROM briefing_log
            WHERE date_key = ? AND completed = 1
        """, (date_key,))
        row = cursor.fetchone()
        return row[0] > 0
    
    def get_drip_state(self, key: str) -> str | None:
        """Read a drip state value from github_state table."""
        cursor = self.connection.execute(
            "SELECT value FROM github_state WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_drip_state(self, key: str, value: str) -> None:
        """Write a drip state value to github_state table."""
        self.connection.execute("""
            INSERT INTO github_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        self.connection.commit()

    # ── Orchestrator Tasks ────────────────────────────────────────

    def create_orchestrator_task(self, task: dict) -> str:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            INSERT INTO orchestrator_tasks (
                id, action_type, tool_name, payload, status,
                requires_confirmation, confirmation_id, autonomy_tier,
                created_at, max_retries, parent_skill_id, skill_step_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task['id'],
            task['action_type'],
            task['tool_name'],
            json.dumps(task['payload']),
            task['status'],
            int(task.get('requires_confirmation', False)),
            task.get('confirmation_id'),
            task['autonomy_tier'],
            now,
            task.get('max_retries', 3),
            task.get('parent_skill_id'),
            task.get('skill_step_index'),
        ))
        self.connection.commit()
        return task['id']

    def get_orchestrator_task(self, task_id: str) -> Optional[dict]:
        cursor = self.connection.execute(
            "SELECT * FROM orchestrator_tasks WHERE id = ?", (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_orchestrator_task(self, task_id: str, updates: dict) -> None:
        allowed = {
            'status', 'started_at', 'completed_at', 'retry_count',
            'last_error', 'result', 'verified', 'verification_result',
            'confirmation_id'
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [task_id]
        self.connection.execute(
            f"UPDATE orchestrator_tasks SET {set_clause} WHERE id = ?",
            values
        )
        self.connection.commit()

    def list_orchestrator_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM orchestrator_tasks WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_last_completed_task_by_tool(
        self, tool_name: str
    ) -> Optional[dict]:
        """Used by Orchestrator for cooldown checks."""
        cursor = self.connection.execute("""
            SELECT * FROM orchestrator_tasks
            WHERE tool_name = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """, (tool_name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Confirmations ─────────────────────────────────────────────

    def create_confirmation(self, confirmation: dict) -> str:
        self.connection.execute("""
            INSERT INTO confirmations (
                id, task_id, action_summary, full_detail,
                status, created_at, expires_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """, (
            confirmation['id'],
            confirmation['task_id'],
            confirmation['action_summary'],
            json.dumps(confirmation['full_detail']),
            confirmation['created_at'],
            confirmation['expires_at'],
        ))
        self.connection.commit()
        return confirmation['id']

    def get_confirmation(self, confirmation_id: str) -> Optional[dict]:
        cursor = self.connection.execute(
            "SELECT * FROM confirmations WHERE id = ?",
            (confirmation_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_pending_confirmations(self) -> list[dict]:
        cursor = self.connection.execute("""
            SELECT * FROM confirmations
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def resolve_confirmation(
        self,
        confirmation_id: str,
        status: str,
        resolved_by: str
    ) -> None:
        now = datetime.utcnow().isoformat()
        self.connection.execute("""
            UPDATE confirmations
            SET status = ?, resolved_at = ?, resolved_by = ?
            WHERE id = ?
        """, (status, now, resolved_by, confirmation_id))
        self.connection.commit()

    def expire_stale_confirmations(self) -> list[str]:
        """
        Mark all pending confirmations past their expires_at
        as expired. Returns list of expired confirmation IDs.
        """
        now = datetime.utcnow().isoformat()
        cursor = self.connection.execute("""
            SELECT id FROM confirmations
            WHERE status = 'pending' AND expires_at < ?
        """, (now,))
        expired_ids = [row[0] for row in cursor.fetchall()]
        if expired_ids:
            placeholders = ",".join("?" * len(expired_ids))
            self.connection.execute(f"""
                UPDATE confirmations
                SET status = 'expired', resolved_at = ?
                WHERE id IN ({placeholders})
            """, [now] + expired_ids)
            self.connection.commit()
        return expired_ids

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        stats = {}
        for table in [
            'task_state', 'decision_log',
            'signal_decay_log', 'session_log',
            'brain_export', 'focus_sessions', 'briefing_log'
        ]:
            cursor = self.connection.execute(
                f"SELECT COUNT(*) as count FROM {table}"
            )
            stats[table] = cursor.fetchone()[0]
        return stats


if __name__ == "__main__":
    print("Initializing MAIHERA SQLite database...")
    db = DatabaseManager()
    db.initialize()
    stats = db.get_stats()
    print("Tables created:")
    for table, count in stats.items():
        print(f"  {table}: {count} rows")
    db.disconnect()
    print("Done.")