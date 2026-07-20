"""Durable Edge inbox for Cloud print-job deliveries.

The database is a local implementation detail of the all-in-one terminal. It
is written before the WebSocket ACK so the Cloud may safely retry a lost ACK
without creating a second physical print.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple


class JobInbox:
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

    def mark_terminal(self, job_id: str, status: str) -> None:
        with self._transaction() as db:
            db.execute("UPDATE print_job_inbox SET state='terminal',terminal_status=?,updated_at=? WHERE job_id=?", (status, time.time(), job_id))

    def recovery(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Return received payloads to resume and interrupted job IDs to flag."""
        with self._transaction() as db:
            received = [json.loads(row[0]) for row in db.execute("SELECT payload FROM print_job_inbox WHERE state='received' ORDER BY received_at")]
            interrupted = [str(row[0]) for row in db.execute("SELECT job_id FROM print_job_inbox WHERE state='processing'")]
            return received, interrupted
