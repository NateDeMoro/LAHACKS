"""Event store: readings, period summaries, risk results and alerts in one SQLite table.
Writes go through a queue so a slow or failing disk never stalls the live tick."""
import asyncio
import contextlib
import json
import logging
import sqlite3
import threading
from collections import deque
from pathlib import Path

from backend.contracts import Model

log = logging.getLogger(__name__)

BATCH = 500
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, kind TEXT, patient_id TEXT, ts TEXT, source TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS events_by_patient ON events (kind, patient_id, ts);
"""


class Store:
    def __init__(self, path: str | Path, queue_max: int = 10_000):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: deque[tuple] = deque(maxlen=queue_max)
        self._wake = asyncio.Event()
        self._lock = threading.Lock()  # a cancel-time flush must wait for a batch still in its worker thread
        self._warned_full = False

    def write(self, kind: str, model: Model, patient_id: str | None = None,
              source: str | None = None) -> None:
        if len(self._queue) == self._queue.maxlen and not self._warned_full:
            self._warned_full = True
            log.warning("store queue full; dropping the oldest rows")
        ts = getattr(model, "ts", None) or getattr(model, "period_ts", None)
        self._queue.append((kind, patient_id, ts.isoformat() if ts else None, source,
                            model.model_dump_json()))
        self._wake.set()

    def fetch(self, kind: str, patient_id: str | None = None) -> list[dict]:
        sql, args = "SELECT payload FROM events WHERE kind = ?", [kind]
        if patient_id is not None:
            sql, args = sql + " AND patient_id = ?", [*args, patient_id]
        with self._lock, self._connect() as con:
            return [json.loads(p) for (p,) in con.execute(sql + " ORDER BY id", args)]

    async def run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._queue:
                    await asyncio.to_thread(self._insert_logged, self._take())
        except asyncio.CancelledError:
            while self._queue:
                self._insert_logged(self._take())
            raise

    def _take(self) -> list[tuple]:
        return [self._queue.popleft() for _ in range(min(BATCH, len(self._queue)))]

    def _insert_logged(self, batch: list[tuple]) -> None:
        try:
            self._insert(batch)
        except sqlite3.Error:
            log.exception("store insert failed; dropping %d rows", len(batch))

    def _insert(self, batch: list[tuple]) -> None:
        with self._lock, self._connect() as con:
            con.executemany(
                "INSERT INTO events (kind, patient_id, ts, source, payload) VALUES (?, ?, ?, ?, ?)", batch)

    @contextlib.contextmanager
    def _connect(self):
        con = sqlite3.connect(self._path)
        try:
            con.executescript(SCHEMA)
            with con:  # commit on success, roll back on error
                yield con
        finally:
            con.close()
