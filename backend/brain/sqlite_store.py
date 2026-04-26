"""
MAIHERA Brain Layer — SQLite Operational Database
Manages task state, decision log, signal decay audit,
session tracking, and brain export/backup.
"""

import os
import sqlite3
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Single interface for all SQLite operations.
    Manages task state, decision log, decay audit,
    session log, and brain export.
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

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        stats = {}
        for table in [
            'task_state', 'decision_log',
            'signal_decay_log', 'session_log', 'brain_export'
        ]:
            cursor = self.connection.execute(
                f"SELECT COUNT(*) as count FROM {table}"
            )
            stats[table] = cursor.fetchone()['count']
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