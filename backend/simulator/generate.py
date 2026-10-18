"""Pure generator for scripted runs: the same script and length always give the same samples."""
import random
from datetime import datetime, timedelta

from backend.contracts import PeriodSummary
from backend.simulator.models import SIM_VITALS, RunScript, Sample, Track


def _line(track: Track, at: float) -> float:
    ks = track.keyframes
    for a, b in zip(ks, ks[1:]):
        if at <= b.at:
            return a.value + (b.value - a.value) * (at - a.at) / (b.at - a.at)
    return ks[-1].value


def _device(track: Track, vital: str, value: float) -> float:
    """Round to the device step; spo2 cannot read above 100."""
    out = round(round(value / track.step) * track.step, 6)  # outer round drops float noise like 38.900000000000006
    return min(out, 100) if vital == "spo2" else out


def _rngs(script: RunScript, salt: str) -> dict[str, random.Random]:
    return {v: random.Random(f"{script.seed}-{v}{salt}") for v in SIM_VITALS}


def keyframe_sample(script: RunScript, at: float) -> Sample:
    """Noise-free value of every track at a fraction of the run."""
    return Sample(**{v: _line(script.tracks[v], at) for v in SIM_VITALS})


def generate(script: RunScript, length_s: int) -> list[Sample]:
    if length_s < 2:
        raise ValueError("a run needs at least 2 seconds")
    rngs = _rngs(script, "")
    glitched = {}
    for g in script.glitches:
        start = round(g.at * (length_s - 1))
        for i in range(start, start + g.duration_s):
            glitched[(g.vital, i)] = g.value
    out = []
    for i in range(length_s):
        at = i / (length_s - 1)
        values = {}
        for v in SIM_VITALS:
            t = script.tracks[v]
            noisy = _line(t, at) + rngs[v].uniform(-t.wobble, t.wobble)  # always draw, so glitches don't shift later noise
            values[v] = glitched[(v, i)] if (v, i) in glitched else _device(t, v, noisy)
        out.append(Sample(**values))
    return out


def preroll_rows(script: RunScript, patient_id: str, run_start: datetime, minutes: int) -> list[PeriodSummary]:
    """One-minute rows at the script's 0:00 values, oldest first, ending the minute before run_start."""
    rngs = _rngs(script, "-preroll")
    start = keyframe_sample(script, 0)
    last = run_start.replace(second=0, microsecond=0) - timedelta(minutes=1)
    rows = []
    for k in range(minutes):
        values = {}
        for v in SIM_VITALS:
            t = script.tracks[v]
            values[v] = _device(t, v, getattr(start, v) + rngs[v].uniform(-t.wobble, t.wobble))
        rows.append(PeriodSummary(patient_id=patient_id, period_ts=last - timedelta(minutes=minutes - 1 - k),
                                  clean_seconds=60, **values))
    return rows
