"""Waiting-room scenario scripts (separate from the single-run scripts in profiles.py).
Keyframes are given in simulated minutes of the 60-minute scenario and converted to run fractions."""
import asyncio
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.config import CONFIG
from backend.contracts import IntakeRecord, Triage, VitalsReading
from backend.simulator.clock import SimClock
from backend.simulator.generate import generate
from backend.simulator.models import Expect, Keyframe, RunScript, Sample, Track
from backend.simulator.profiles import PROFILES
from backend.timeutil import now_la

SCENARIO_MINUTES = 60
_WOBBLE_STEP = {"hr": (2, 1), "resp_rate": (1, 1), "spo2": (0.8, 1), "temp_c": (0.05, 0.1)}


def minute_script(points: dict[str, list[tuple[float, float]]], seed: int, news2: list[int], alerts: str) -> RunScript:
    tracks = {
        v: Track(keyframes=[Keyframe(at=m / SCENARIO_MINUTES, value=x) for m, x in pts],
                 wobble=_WOBBLE_STEP[v][0], step=_WOBBLE_STEP[v][1])
        for v, pts in points.items()
    }
    return RunScript(tracks=tracks, seed=seed, expect=Expect(news2=news2, alerts=alerts))


# Steep-then-hold: change between minutes 12 and 22, hold just short of danger, then drop into danger from 31.
JOHN_POINTS = {
    "hr": [(0, 76), (12, 76), (22, 84), (31, 86), (33, 102), (60, 104)],
    "resp_rate": [(0, 15), (12, 15), (22, 24), (31, 24), (33, 27), (60, 27)],
    "spo2": [(0, 98), (12, 98), (22, 92), (31, 92), (33, 90), (60, 90)],
    "temp_c": [(0, 36.7), (31, 36.8), (33, 38.4), (60, 38.6)],
}
JOHN_SCRIPT = minute_script(JOHN_POINTS, 107, [0, 0, 3, 8],
                            "Trend alert by about minute 28, high NEWS2 8 alert by minute 45")


def _flat(hr, rr, spo2, temp, hr2=None, rr2=None, spo22=None, temp2=None):
    """Mild drift from the first to the last minute."""
    return {"hr": [(0, hr), (60, hr2 if hr2 is not None else hr)],
            "resp_rate": [(0, rr), (60, rr2 if rr2 is not None else rr)],
            "spo2": [(0, spo2), (60, spo22 if spo22 is not None else spo2)],
            "temp_c": [(0, temp), (60, temp2 if temp2 is not None else temp)]}


def _rec(profile_id: str, **update) -> IntakeRecord:
    return PROFILES[profile_id].record.model_copy(update=update)


@dataclass(frozen=True)
class ScenarioPatient:
    key: str
    name: str
    wearable_id: int
    record: IntakeRecord
    script: RunScript


def _john_record() -> IntakeRecord:
    return IntakeRecord(
        patient_id="sim-john", age=54, sex="male", height_cm=180, weight_kg=84, pregnant=False,
        conditions=[], medications=[], chief_complaint="Feeling run down, a cough that is getting worse.",
        triage=Triage(sbp=124, dbp=80, alertness="alert", pain=2, on_oxygen=False, level=3))


_W = CONFIG.simulator.scenario_wearable_ids
# Order is bed order. H1 is called in at CALLED_IN_MINUTE; John replaces U2; C1 and C2 stay below high.
SCENARIO_PATIENTS = [
    ScenarioPatient("h1", "Marcus Webb", _W[0], _rec("h1"),
                    minute_script(_flat(72, 14, 98, 36.6), 201, [0] * 4, "None")),
    ScenarioPatient("h2", "Priya Nair", _W[1], _rec("h2"),
                    minute_script(_flat(78, 15, 97, 36.8, 80, 15, 97, 36.8), 202, [0] * 4, "None")),
    ScenarioPatient("u1", "Walter Hobbs", _W[2], _rec("u1"),
                    minute_script(_flat(82, 18, 96, 37.4, 90, 19, 95, 37.4), 203, [1, 1, 2, 2], "Amber at most")),
    ScenarioPatient("john", "John Chamberlain", _W[3], _john_record(), JOHN_SCRIPT),
    ScenarioPatient("c1", "Elena Ruiz", _W[4],
                    _rec("c1", triage=Triage(sbp=112, dbp=70, alertness="alert", pain=2, on_oxygen=False, level=2)),
                    minute_script(_flat(90, 20, 95, 36.8, 96, 21, 94, 36.9), 204, [1, 2, 3, 4], "Below high")),
    ScenarioPatient("c2", "Dorothy Klein", _W[5],
                    _rec("c2", triage=Triage(sbp=108, dbp=66, alertness="alert", pain=0, on_oxygen=False, level=2)),
                    minute_script(_flat(94, 19, 96, 37.4, 98, 20, 96, 37.5), 205, [1, 2, 3, 4], "Below high")),
]

CALLED_IN_KEY, CALLED_IN_MINUTE = "h1", 25
LEAD_IN_MINUTES = 20


class ScenarioRunner:
    """The waiting room: starts the six patients, plays their scripts on a sim clock, and replays skips.
    Use when POST /sim/scenario or /sim/skip arrives."""

    def __init__(self, service, intake, registry, *, now=time.monotonic, sleep=asyncio.sleep):
        self._svc, self._intake, self._registry = service, intake, registry
        self._now, self._sleep = now, sleep
        self.clock = SimClock()
        self._start_ts: datetime | None = None
        self._ids: dict[str, str] = {}  # patient key -> this run's patient_id
        self._active: set[str] = set()  # patient keys still being monitored
        self._samples: dict[str, list[Sample]] = {}
        self._pos = 0  # next sim second to play
        self._skip: tuple[int, asyncio.Event] | None = None
        self.at_end = False

    @property
    def total_s(self) -> int:
        return SCENARIO_MINUTES * 60

    def sim_now(self) -> datetime | None:
        return self.clock() if self._start_ts else None

    async def prepare(self) -> None:
        """Registers the six patients through intake and replays the lead-in. Needs the event loop."""
        await self.drop_all()
        self._start_ts = now_la().replace(second=0, microsecond=0)
        self.clock.freeze(self._start_ts)
        run = secrets.token_hex(2)
        self.at_end, self._pos = False, 0
        for p in SCENARIO_PATIENTS:
            pid = self._ids[p.key] = f"{p.record.patient_id}-{run}"
            self._samples[p.key] = generate(p.script, self.total_s)
            self._svc.set_clock(pid, self.clock)
            rec = p.record.model_copy(update={"patient_id": pid, "name": p.name, "wearable_id": p.wearable_id,
                                              "arrival_ts": self._start_ts})
            await self._intake.submit(rec, structured_only=True)
            self._svc.set_run_state(pid, "running")
            self._active.add(p.key)
        await self._replay(LEAD_IN_MINUTES * 60)

    async def play(self) -> None:
        """The player task. Plays one sim second per wall second and serves skip requests between seconds."""
        try:
            t0, base = self._now(), self._pos
            while self._pos < self.total_s:
                if self._skip:
                    target, done = self._skip
                    await self._replay(min(target, self.total_s))
                    t0, base = self._now(), self._pos  # the replay's own duration must not stretch the clock
                    self._skip = None
                    if self._pos >= self.total_s:
                        self._end()
                    done.set()
                    continue
                await self._sleep(max(0, t0 + (self._pos - base) - self._now()))
                if self._skip:
                    continue
                self._step(self._pos)
                self._pos += 1
            self._end()
        finally:
            self._end()
            if self._skip:
                self._skip[1].set()

    async def skip(self, minutes: float) -> None:
        if self._skip:
            raise RuntimeError("a skip is already running")
        done = asyncio.Event()
        self._skip = (min(self._pos + round(minutes * 60), self.total_s), done)
        await done.wait()

    def _end(self) -> None:
        if self.at_end:
            return
        self.at_end = True
        for key in list(self._active):
            self._svc.set_run_state(self._ids[key], "ended")

    async def _replay(self, target: int) -> None:
        """Plays every second up to `target` at once, on a frozen clock; I13 and I14 go out for the last second only."""
        self._svc.replaying = True
        try:
            while self._pos < target:
                self.clock.freeze(self._start_ts + timedelta(seconds=self._pos + 1))
                self._step(self._pos)
                if self._pos == target - 1:
                    self._svc.replaying = False
                self._svc.tick([self._ids[k] for k in self._active])
                self._pos += 1
                if self._pos % 60 == 0:
                    await asyncio.sleep(0)  # let the server answer others between minutes
        finally:
            self._svc.replaying = False
            self.clock.anchor(self._start_ts + timedelta(seconds=self._pos))

    def _step(self, i: int) -> None:
        ts = self._start_ts + timedelta(seconds=i)
        if i == CALLED_IN_MINUTE * 60 and CALLED_IN_KEY in self._active:
            self.call_in(self._ids[CALLED_IN_KEY], ts)
        for key in self._active:
            pid = self._ids[key]
            w = self._svc.wearable_of(pid)  # follows a strap swap from the sensor modal
            s = self._samples[key][i]
            self._svc.ingest(VitalsReading(wearable_id=w, ts=ts, hr=s.hr, resp_rate=s.resp_rate, spo2=s.spo2,
                                           temp_c=s.temp_c, contact=True), "simulator")

    def call_in(self, patient_id: str, ts: datetime | None = None) -> None:
        """The patient is called in: stamped on the registry and monitoring ends."""
        key = next((k for k, p in self._ids.items() if p == patient_id), None)
        self._registry.mark_called_in(patient_id, ts or self.clock())
        if key in self._active:
            self._active.discard(key)
            self._svc.drop(patient_id)

    async def drop_all(self) -> None:
        for pid in self._ids.values():
            self._svc.drop(pid)
        self._registry.forget_simulated()
        self._ids.clear(); self._active.clear(); self._samples.clear()
        self._start_ts, self._pos, self._skip = None, 0, None
        self.clock.anchor(now_la())
