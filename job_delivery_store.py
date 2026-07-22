"""Durable Edge delivery state for Cloud print jobs and terminal reports."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class JobDeliveryStore:
    """One SQLite transaction boundary for inbound jobs and terminal reports."""

    def __init__(self, path: str):
        self.path = str(Path(path))
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS print_job_inbox (
                job_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('received','processing','terminal')),
                terminal_status TEXT, received_at REAL NOT NULL, updated_at REAL NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS terminal_job_report_outbox (
                event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','rejected')),
                attempt_count INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
                last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_terminal_report_outbox_due ON terminal_job_report_outbox(state,next_attempt_at)")

    @contextmanager
    def _transaction(self):
        with self._lock:
            db = self._connect()
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def receive(self, job_id: str, message_id: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        now = time.time()
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with self._transaction() as db:
            row = db.execute("SELECT state FROM print_job_inbox WHERE job_id=?", (job_id,)).fetchone()
            if row:
                return False, str(row[0])
            db.execute("INSERT INTO print_job_inbox(job_id,message_id,payload,state,received_at,updated_at) VALUES(?,?,?,'received',?,?)", (job_id, message_id, encoded, now, now))
            return True, "received"

    def mark_processing(self, job_id: str) -> bool:
        with self._transaction() as db:
            result = db.execute("UPDATE print_job_inbox SET state='processing',updated_at=? WHERE job_id=? AND state='received'", (time.time(), job_id))
            return result.rowcount == 1

    def record_terminal_report(self, job_id: str, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist local finality and exactly one stable Cloud report together."""
        now = time.time()
        with self._transaction() as db:
            row = db.execute("SELECT payload FROM terminal_job_report_outbox WHERE job_id=?", (job_id,)).fetchone()
            db.execute("UPDATE print_job_inbox SET state='terminal',terminal_status=?,updated_at=? WHERE job_id=?", (status, now, job_id))
            if row:
                return json.loads(str(row[0]))
            event_id = str(uuid.uuid4())
            report = dict(payload)
            report["event_id"] = event_id
            encoded = json.dumps(report, separators=(",", ":"), ensure_ascii=False)
            db.execute("""INSERT INTO terminal_job_report_outbox(event_id,job_id,status,payload,state,next_attempt_at,created_at,updated_at)
                VALUES(?,?,?,?, 'pending',?,?,?)""", (event_id, job_id, status, encoded, now, now, now))
            return report

    def recovery(self) -> Tuple[List[Dict[str, Any]], List[Tuple[str, Dict[str, Any]]]]:
        with self._transaction() as db:
            received = [json.loads(row[0]) for row in db.execute("SELECT payload FROM print_job_inbox WHERE state='received' ORDER BY received_at")]
            interrupted = [
                (str(row[0]), json.loads(row[1]))
                for row in db.execute("SELECT job_id, payload FROM print_job_inbox WHERE state='processing'")
            ]
            return received, interrupted

    def due_terminal_reports(self, now: Optional[float] = None, limit: int = 100) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        with self._transaction() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM terminal_job_report_outbox WHERE state='pending' AND next_attempt_at<=? ORDER BY created_at LIMIT ?", (now, limit))]

    def schedule_terminal_report_retry(self, event_id: str, error: str = "") -> None:
        with self._transaction() as db:
            row = db.execute("SELECT attempt_count FROM terminal_job_report_outbox WHERE event_id=? AND state='pending'", (event_id,)).fetchone()
            if not row:
                return
            attempts = int(row[0]) + 1
            delay = min(60.0, float(2 ** min(attempts - 1, 6)))
            db.execute("UPDATE terminal_job_report_outbox SET attempt_count=?,next_attempt_at=?,last_error=?,updated_at=? WHERE event_id=?", (attempts, time.time() + delay, error, time.time(), event_id))

    def acknowledge_terminal_report(self, event_id: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM terminal_job_report_outbox WHERE event_id=? AND state='pending'", (event_id,))

    def reject_terminal_report(self, event_id: str, reason: str) -> None:
        with self._transaction() as db:
            db.execute("UPDATE terminal_job_report_outbox SET state='rejected',last_error=?,updated_at=? WHERE event_id=? AND state='pending'", (reason, time.time(), event_id))

    def report_summary(self) -> Dict[str, Any]:
        with self._transaction() as db:
            pending = db.execute("SELECT COUNT(*) FROM terminal_job_report_outbox WHERE state='pending'").fetchone()[0]
            rejected = db.execute("SELECT COUNT(*) FROM terminal_job_report_outbox WHERE state='rejected'").fetchone()[0]
            last = db.execute("SELECT event_id,job_id,last_error FROM terminal_job_report_outbox WHERE state='rejected' ORDER BY updated_at DESC LIMIT 1").fetchone()
            return {"pending": int(pending), "rejected": int(rejected), "last_rejected": {"event_id": last[0], "job_id": last[1], "reason": last[2]} if last else None}
