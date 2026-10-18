"""Tiger Data (TimescaleDB) mirror of the event store. Optional: built only when TIGER_DATA_URL is set.
Same write/run shape as Store, but every failure disables or drops rows; it can never stall ingest or shutdown."""
import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb

from backend.contracts import Model

log = logging.getLogger(__name__)

BATCH = 500
CONNECT_TIMEOUT_S = 3
STATEMENT_TIMEOUT_MS = 5000
VITALS = ("hr", "spo2", "resp_rate", "temp_c")

# One statement each, run on an autocommit connection (a continuous aggregate can't be created in a transaction).
SCHEMA = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit",
    """CREATE TABLE IF NOT EXISTS readings (
        ts timestamptz NOT NULL, patient_id text, kind text NOT NULL, source text, payload jsonb,
        hr double precision, spo2 double precision, resp_rate double precision, temp_c double precision)""",
    "SELECT create_hypertable('readings', 'ts', if_not_exists => true)",
    # percentile_agg because exact percentile_cont isn't allowed in continuous aggregates
    """CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1m WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 minute', ts) AS bucket, patient_id,
               percentile_agg(hr) AS hr_agg, percentile_agg(spo2) AS spo2_agg,
               percentile_agg(resp_rate) AS resp_rate_agg, percentile_agg(temp_c) AS temp_c_agg
        FROM readings WHERE kind = 'I1' GROUP BY bucket, patient_id WITH NO DATA""",
    # real-time view so the scenario's skipped-ahead sim time shows before a refresh runs
    "ALTER MATERIALIZED VIEW readings_1m SET (timescaledb.materialized_only = false)",
    """SELECT add_continuous_aggregate_policy('readings_1m', start_offset => INTERVAL '1 day',
        end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => true)""",
]
# Nice to have; a failure here (older Timescale, no columnstore) is only logged. Each entry is a list of fallbacks.
OPTIONAL = [
    ["ALTER TABLE readings SET (timescaledb.enable_columnstore = true, timescaledb.segmentby = 'patient_id')",
     "ALTER TABLE readings SET (timescaledb.compress, timescaledb.compress_segmentby = 'patient_id')"],
    ["CALL add_columnstore_policy('readings', after => INTERVAL '7 days', if_not_exists => true)",
     "SELECT add_compression_policy('readings', INTERVAL '7 days', if_not_exists => true)"],
]
INSERT = ("INSERT INTO readings (ts, patient_id, kind, source, payload, hr, spo2, resp_rate, temp_c) "
          "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")
MINUTES = ("SELECT bucket, approx_percentile(0.5, hr_agg), approx_percentile(0.5, spo2_agg), "
           "approx_percentile(0.5, resp_rate_agg), approx_percentile(0.5, temp_c_agg) "
           "FROM readings_1m WHERE patient_id = %s ORDER BY bucket DESC LIMIT %s")


class TigerMirror:
    def __init__(self, url: str, queue_max: int = 10_000):
        self._url = url
        self._queue: deque[tuple] = deque(maxlen=queue_max)
        self._wake = asyncio.Event()
        self._enabled = True
        self._warned = False

    def write(self, kind: str, model: Model, patient_id: str | None = None,
              source: str | None = None) -> None:
        if not self._enabled:
            return
        ts = getattr(model, "ts", None) or getattr(model, "period_ts", None) or datetime.now(timezone.utc)
        vitals = [getattr(model, v, None) if kind == "I1" else None for v in VITALS]
        self._queue.append((ts, patient_id, kind, source, Jsonb(model.model_dump(mode="json")), *vitals))
        self._wake.set()

    async def run(self) -> None:
        con = None
        try:
            con = await asyncio.to_thread(self._setup)
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._queue and self._enabled:
                    batch = [self._queue.popleft() for _ in range(min(BATCH, len(self._queue)))]
                    con = await asyncio.to_thread(self._insert, con, batch)
        except asyncio.CancelledError:
            self._queue.clear()  # drop, don't flush: an unreachable Tiger must not hold up shutdown
            raise
        except Exception as e:
            log.warning("tiger mirror disabled: %r", e)
            self._enabled = False
            self._queue.clear()
        finally:
            if con is not None:
                con.close()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True,
                               options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}")

    def _setup(self) -> psycopg.Connection:
        con = self._connect()
        try:
            con.execute("SET statement_timeout = '30s'")  # DDL and the first extension load are slower than inserts
            for sql in SCHEMA:
                con.execute(sql)
            for fallbacks in OPTIONAL:
                for sql in fallbacks:
                    try:
                        con.execute(sql)
                        break
                    except psycopg.Error as e:
                        log.info("tiger optional setup step skipped: %r", e)
            con.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            return con
        except Exception:
            con.close()
            raise

    def _insert(self, con: psycopg.Connection | None, batch: list[tuple]) -> psycopg.Connection | None:
        try:
            con = con or self._connect()
            with con.cursor() as cur:
                cur.executemany(INSERT, batch)
            return con
        except psycopg.Error as e:
            if not self._warned:
                self._warned = True
                log.warning("tiger insert failed; dropping %d rows (further failures are silent): %r", len(batch), e)
            if con is not None:
                con.close()
            return None

    def minutes(self, patient_id: str, limit: int) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(MINUTES, (patient_id, limit)).fetchall()
        return [{"bucket": r[0].isoformat(), **dict(zip(VITALS, r[1:]))} for r in rows]


def build_router(mirror: TigerMirror) -> APIRouter:
    router = APIRouter(prefix="/tiger")

    @router.get("/minutes/{patient_id}")
    def minutes(patient_id: str, limit: int = 60):  # plain def: runs in the threadpool, not the event loop
        try:
            return mirror.minutes(patient_id, limit)
        except psycopg.Error as e:
            raise HTTPException(503, f"tiger unavailable: {e}")

    return router
