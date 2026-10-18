"""One patient's readings, turned into I13 (every tick) and I6 (every period). Pure: the caller
passes the clock, so a replay or a test can run it faster than real time."""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from backend.config import CONFIG, IngestConfig
from backend.contracts import LiveWindow, PeriodSummary, RunState, VitalsReading, VitalValues
from backend.simulator.models import Source

VITALS = ("hr", "resp_rate", "spo2", "temp_c")


@dataclass(frozen=True)
class Tick:
    live: LiveWindow
    period: PeriodSummary | None


@dataclass(frozen=True)
class _Sample:
    ts: datetime
    clean: bool
    values: dict[str, float]


class PatientStream:
    def __init__(self, patient_id: str, now: datetime, cfg: IngestConfig = CONFIG.ingest):
        self.patient_id = patient_id
        self.run_state: RunState = "live"
        self._cfg = cfg
        self._start(now)

    def _start(self, now: datetime) -> None:
        """Clears everything; minutes count from here, so a run gives whole minutes."""
        self._period_start = now
        self._window: deque[_Sample] = deque(maxlen=int(self._cfg.window_s))  # ticks can jitter; never hold more seconds than the window
        self._period: list[_Sample] = []
        self._strap: tuple[datetime, VitalsReading] | None = None
        self._sim: dict[str, tuple[datetime, float]] = {}
        self._sim_contact: tuple[datetime, bool] | None = None
        self._frozen: LiveWindow | None = None

    def set_run_state(self, now: datetime, state: RunState) -> PeriodSummary | None:
        """Returns the period left open when a run ends: no tick will close it once the window is frozen."""
        last = None
        if state == "ended" and self.run_state != "ended":
            last = self._summarise_period() if self._period else None
            self._frozen = self._live(now).model_copy(update={"run_state": "ended"})
        elif state != self.run_state:
            self._start(now)
        self.run_state = state
        return last

    def on_reading(self, now: datetime, reading: VitalsReading, source: Source) -> bool:
        """False when the reading is not kept (run mode ignores the strap, an ended run ignores everything)."""
        if self.run_state == "ended" or (source == "strap" and self.run_state == "running"):
            return False
        if source == "strap":
            self._strap = (now, reading)
            return True
        for v in VITALS:
            if (val := getattr(reading, v)) is not None:
                self._sim[v] = (now, val)
        if reading.contact is not None:
            self._sim_contact = (now, reading.contact)
        return True

    def tick(self, now: datetime) -> Tick:
        if self.run_state == "ended":
            return Tick(self._frozen.model_copy(update={"window_end_ts": now}), None)
        period = self._close_period(now)
        sample = self._sample(now)
        self._window.append(sample)
        self._period.append(sample)
        return Tick(self._live(now), period)

    def _fresh(self, ts: datetime, now: datetime, ttl: float) -> bool:
        return now - ts <= timedelta(seconds=ttl)

    def _sample(self, now: datetime) -> _Sample:
        cfg = self._cfg
        strap = self._strap[1] if self._strap and self._fresh(self._strap[0], now, cfg.strap_ttl_s) else None
        merged: dict[str, float | None] = {}
        for v in VITALS:
            if v in cfg.disabled_vitals:
                continue
            sim = self._sim.get(v)
            if sim and self._fresh(sim[0], now, cfg.sim_ttl_s):
                merged[v] = sim[1]
            else:
                merged[v] = getattr(strap, v, None) if strap else None
        hr_from_sim = (v := self._sim.get("hr")) is not None and self._fresh(v[0], now, cfg.sim_ttl_s)
        if hr_from_sim:  # the simulator only sets contact beside readings, and always true
            contact = self._sim_contact is None or self._sim_contact[1]
        else:
            contact = bool(strap and strap.contact)
        values = {v: x for v, x in merged.items() if x is not None and cfg.bounds[v][0] <= x <= cfg.bounds[v][1]}
        return _Sample(now, "hr" in values and contact, values)

    def _live(self, now: datetime) -> LiveWindow:
        cutoff = now - timedelta(seconds=self._cfg.window_s)
        while self._window and self._window[0].ts <= cutoff:
            self._window.popleft()
        med, seconds = self._medians(self._window, self._cfg.min_samples)
        newest = self._window[-1] if self._window else None
        latest = VitalValues(**newest.values) if newest and newest.clean else None
        return LiveWindow(patient_id=self.patient_id, window_end_ts=now, clean_seconds=seconds,
                          latest=latest, run_state=self.run_state, **med)

    def _close_period(self, now: datetime) -> PeriodSummary | None:
        length = timedelta(seconds=self._cfg.window_s)
        if now < self._period_start + length:
            return None
        out = self._summarise_period()
        # After a stall, jump to the period that contains now instead of emitting empty rows.
        self._period_start += length * ((now - self._period_start) // length)
        self._period = []
        return out

    def _summarise_period(self) -> PeriodSummary:
        med, seconds = self._medians(self._period, 1)
        return PeriodSummary(patient_id=self.patient_id, period_ts=self._period_start,
                             clean_seconds=seconds, **med)

    @staticmethod
    def _medians(samples, need: int) -> tuple[dict[str, float | None], int]:
        clean = [s for s in samples if s.clean]
        med = {}
        for v in VITALS:
            xs = [s.values[v] for s in clean if v in s.values]
            med[v] = round(median(xs), 3) if len(xs) >= need else None
        return med, len(clean)
