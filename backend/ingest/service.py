"""Ingest service (S2): routes readings to per-patient streams, and on every tick runs the pipeline
I13 -> engine (I14), and at each minute close I6 -> engine (I9) -> alert logic (I10)."""
import asyncio
import logging
from datetime import datetime
from typing import Callable

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
                 on_drop: Callable[[str], None] = lambda patient_id: None):
        self.engine, self._alerts, self._publish, self._store = engine, alerts, publish, store
        self._cfg, self._clock, self._on_drop = cfg, clock, on_drop
        self._ranges_sent: set[str] = set()
        self._wearables: dict[int, str] = {}
        self._streams: dict[str, PatientStream] = {}
        self._unassigned_logged: dict[int | None, datetime] = {}
        engine.ranges_listener = self._push_ranges
        for wearable_id, patient_id in cfg.default_assignments.items():
            self.assign(wearable_id, patient_id)

    def assign(self, wearable_id: int, patient_id: str) -> None:
        """I3. A wearable has one patient and a patient one wearable; a patient left with no wearable is dropped."""
        old = self._wearables.get(wearable_id)
        for w in [w for w, p in self._wearables.items() if p == patient_id and w != wearable_id]:
            del self._wearables[w]
        self._wearables[wearable_id] = patient_id
        if old is not None and old != patient_id and old not in self._wearables.values():
            self._streams.pop(old, None)
            self._ranges_sent.discard(old)  # it may come back, and the engine will not announce unchanged ranges
            self._on_drop(old)
        if patient_id not in self._streams:
            self._streams[patient_id] = PatientStream(patient_id, self._clock(), self._cfg)

    def wearable_of(self, patient_id: str | None) -> int | None:
        return next((w for w, p in self._wearables.items() if p == patient_id), None)

    def ingest(self, reading: VitalsReading, source: Source) -> None:
        now = self._clock()
        patient_id = self._wearables.get(reading.wearable_id)
        if patient_id is None:
            self._log_unassigned(reading.wearable_id, now)
            return
        if self._streams[patient_id].on_reading(now, reading, source):
            self._store.write("I1", reading, patient_id, source)

    def set_run_state(self, patient_id: str, state: RunState) -> None:
        stream = self._streams.get(patient_id)
        if stream is None:
            log.warning("run state %s for unknown patient %s ignored", state, patient_id)
            return
        if last := stream.set_run_state(self._clock(), state):
            self._close_minute(last)

    def seed_trend_history(self, patient_id: str, rows: list) -> None:
        seed = getattr(self.engine, "seed_trend_history", None)  # the engine does not have it yet (T6)
        if seed:
            seed(patient_id, rows)

    def on_ack(self, ack: Acknowledgment) -> bool:
        return self._alerts.on_ack(ack)

    def tick(self) -> None:
        now = self._clock()
        for stream in list(self._streams.values()):
            try:
                self._tick_one(stream, now)
            except Exception:
                log.exception("tick failed for %s", stream.patient_id)

    def _tick_one(self, stream: PatientStream, now: datetime) -> None:
        tick = stream.tick(now)
        self._publish("I13", tick.live)
        try:
            self._publish("I14", self.engine.on_second(tick.live))
        finally:  # the minute still closes if the second's scoring failed
            if tick.minute:
                self._close_minute(tick.minute)

    def _close_minute(self, minute) -> None:
        self._store.write("I6", minute, minute.patient_id)
        risk = self.engine.on_minute(minute)
        if minute.patient_id not in self._ranges_sent:  # the engine only announces ranges once they change
            self._push_ranges(self.engine.ranges[minute.patient_id])
        self._publish("I9", risk)
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
            self.tick()
