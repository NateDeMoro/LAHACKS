"""Ingest service (S2): routes readings to per-patient streams, and on every tick runs the pipeline
I13 -> engine (I14), and at each period close I6 -> engine (I9) -> alert logic (I10)."""
import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Callable

import sentry_sdk

from backend.config import CONFIG, IngestConfig
from backend.contracts import Acknowledgment, Model, RunState, VitalsReading
from backend.ingest.stream import PatientStream
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine
from backend.simulator.models import Source
from backend.timeutil import now_la

log = logging.getLogger(__name__)


class IngestService:
    def __init__(self, engine: RiskEngine, alerts: AlertLogic, publish: Callable[[str, Model], None],
                 store, cfg: IngestConfig = CONFIG.ingest, *, clock: Callable[[], datetime] = now_la,
                 on_drop: Callable[[str], None] = lambda patient_id: None,
                 on_risk: Callable[[Model], None] = lambda risk: None):
        self.engine, self._alerts, self._publish, self._store = engine, alerts, publish, store
        self._cfg, self._clock, self._on_drop, self._on_risk = cfg, clock, on_drop, on_risk
        self._clocks: dict[str, Callable[[], datetime]] = {}  # scenario patients run on a sim clock, the rest on wall time
        self.replaying = False  # true while a skip is replayed: scenario patients publish no I13/I14 and store no I1
        self._ranges_sent: set[str] = set()
        self._wearables: dict[int, str] = {}
        self._streams: dict[str, PatientStream] = {}
        self._unassigned_logged: dict[int | None, datetime] = {}
        engine.ranges_listener = self._push_ranges
        for wearable_id, patient_id in cfg.default_assignments.items():
            self.assign(wearable_id, patient_id)

    def set_clock(self, patient_id: str, clock: Callable[[], datetime]) -> None:
        """Use before assign() for a patient who runs on a sim clock."""
        self._clocks[patient_id] = clock

    def _now(self, patient_id: str) -> datetime:
        return self._clocks.get(patient_id, self._clock)()

    def drop(self, patient_id: str) -> None:
        """Stops monitoring a patient: stream, wearable and clock go, and the hub forgets them."""
        self._streams.pop(patient_id, None)
        self._clocks.pop(patient_id, None)
        self._ranges_sent.discard(patient_id)
        for w in [w for w, p in self._wearables.items() if p == patient_id]:
            del self._wearables[w]
        self._on_drop(patient_id)

    def assign(self, wearable_id: int, patient_id: str) -> None:
        """I3. A wearable has one patient and a patient one wearable; a patient left with no wearable is dropped."""
        old = self._wearables.get(wearable_id)
        for w in [w for w, p in self._wearables.items() if p == patient_id and w != wearable_id]:
            del self._wearables[w]
        self._wearables[wearable_id] = patient_id
        if old is not None and old != patient_id and old not in self._wearables.values():
            self._streams.pop(old, None)
            self._clocks.pop(old, None)
            self._ranges_sent.discard(old)  # it may come back, and the engine will not announce unchanged ranges
            self._on_drop(old)
        if patient_id not in self._streams:
            self._streams[patient_id] = PatientStream(patient_id, self._now(patient_id), self._cfg)

    def wearable_of(self, patient_id: str | None) -> int | None:
        return next((w for w, p in self._wearables.items() if p == patient_id), None)

    def ingest(self, reading: VitalsReading, source: Source) -> None:
        patient_id = self._wearables.get(reading.wearable_id)
        if patient_id is None:
            self._log_unassigned(reading.wearable_id, self._clock())
            return
        now = self._now(patient_id)
        if self._streams[patient_id].on_reading(now, reading, source):
            if self.replaying and patient_id in self._clocks:
                return
            self._store.write("I1", reading, patient_id, source)

    def set_run_state(self, patient_id: str, state: RunState) -> None:
        stream = self._streams.get(patient_id)
        if stream is None:
            log.warning("run state %s for unknown patient %s ignored", state, patient_id)
            return
        if last := stream.set_run_state(self._now(patient_id), state):
            self._close_period(last)

    def seed_trend_history(self, patient_id: str, rows: list) -> None:
        seed = getattr(self.engine, "seed_trend_history", None)  # the engine does not have it yet (T6)
        if seed:
            seed(patient_id, rows)

    def on_ack(self, ack: Acknowledgment) -> bool:
        return self._alerts.on_ack(ack)

    def _txn(self, op: str, name: str):
        """A Sentry transaction, except during a skip replay, which runs thousands of ticks in one burst."""
        return contextlib.nullcontext() if self.replaying else sentry_sdk.start_transaction(op=op, name=name)

    def tick(self, only: list[str] | None = None, *, skip_sim: bool = False) -> None:
        """One second for every stream, or just the patients in `only`. skip_sim leaves the scenario patients out."""
        with self._txn("ingest.tick", "ingest tick"):
            for stream in list(self._streams.values()):
                pid = stream.patient_id
                if (only is not None and pid not in only) or (skip_sim and pid in self._clocks):
                    continue
                try:
                    self._tick_one(stream, self._now(pid))
                except Exception:
                    log.exception("tick failed for %s", stream.patient_id)

    def _tick_one(self, stream: PatientStream, now: datetime) -> None:
        tick = stream.tick(now)
        quiet = self.replaying and stream.patient_id in self._clocks
        if not quiet:
            self._publish("I13", tick.live)
        try:
            with sentry_sdk.start_span(op="engine.second", name="news2"):
                news2 = self.engine.on_second(tick.live)
            if not quiet:
                self._publish("I14", news2)
        finally:  # the period still closes if the second's scoring failed
            if tick.period:
                self._close_period(tick.period)

    def _close_period(self, period) -> None:
        with self._txn("engine.period", "engine period"):  # kept in full and profiled
            self._store.write("I6", period, period.patient_id)
            with sentry_sdk.start_span(op="engine.period", name="baseline and trend"):
                risk = self.engine.on_period(period)
            if period.patient_id not in self._ranges_sent:  # the engine only announces ranges once they change
                self._push_ranges(self.engine.ranges[period.patient_id])
            self._publish("I9", risk)
            self._on_risk(risk)
            self._store.write("I9", risk, risk.patient_id)
            for alert in self._alerts.on_risk(risk):
                self._publish("I10", alert)
                self._store.write("I10", alert, alert.patient_id)

    def _push_ranges(self, ranges) -> None:
        self._ranges_sent.add(ranges.patient_id)
        self._publish("I8", ranges)

    def _log_unassigned(self, wearable_id: int | None, now: datetime) -> None:
        last = self._unassigned_logged.get(wearable_id)
        if last is None or (now - last).total_seconds() >= self._cfg.unassigned_log_every_s:
            self._unassigned_logged[wearable_id] = now
            log.warning("reading from unassigned wearable %s dropped", wearable_id)

    async def run(self) -> None:
        """Ticks on the wall-clock second until cancelled."""
        while True:
            now = self._clock()
            await asyncio.sleep(1 - now.microsecond / 1e6)
            self.tick(skip_sim=self.replaying)
