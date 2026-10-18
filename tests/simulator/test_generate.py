from datetime import datetime, timedelta, timezone

import pytest

from backend.simulator.generate import generate, keyframe_sample, preroll_rows
from backend.simulator.models import SIM_VITALS, Keyframe, Track
from backend.simulator.profiles import PROFILES

LENGTHS = (600, 300)


def _tol(script, vital):
    t = script.tracks[vital]
    return t.wobble + t.step / 2 + 1e-9


@pytest.mark.parametrize("pid", list(PROFILES))
def test_generate_is_deterministic_and_exact_length(pid):
    script = PROFILES[pid].script
    for n in LENGTHS:
        out = generate(script, n)
        assert len(out) == n
        assert out == generate(script, n)


@pytest.mark.parametrize("n", LENGTHS)
@pytest.mark.parametrize("pid", list(PROFILES))
def test_samples_follow_the_line_and_look_like_a_device(pid, n):
    script = PROFILES[pid].script
    steady = [v for v in SIM_VITALS if not any(g.vital == v for g in script.glitches)]
    for i, s in enumerate(generate(script, n)):
        line = keyframe_sample(script, i / (n - 1))  # also pins the ends and the 60% key to the same fractions at any length
        for v in steady:
            assert abs(getattr(s, v) - getattr(line, v)) <= _tol(script, v), (v, i)
        assert float(s.hr).is_integer() and float(s.resp_rate).is_integer() and float(s.spo2).is_integer()
        assert s.temp_c == round(s.temp_c, 1)


def test_spo2_never_reads_above_100():
    script = PROFILES["h1"].script
    flat_100 = Track(keyframes=[Keyframe(at=0, value=100), Keyframe(at=1, value=100)], wobble=1.5, step=1)
    script = script.model_copy(update={"tracks": {**script.tracks, "spo2": flat_100}, "glitches": []})
    readings = [s.spo2 for s in generate(script, 300)]
    assert max(readings) == 100 and min(readings) >= 98


def test_h1_spo2_glitch_is_exact():
    script = PROFILES["h1"].script
    n = 600
    start = round(0.5 * (n - 1))
    hits = [i for i, s in enumerate(generate(script, n)) if s.spo2 == 90]
    assert hits == list(range(start, start + 8))


def test_a_run_under_two_seconds_is_rejected():
    with pytest.raises(ValueError):
        generate(PROFILES["h1"].script, 1)


def test_preroll_rows():
    script = PROFILES["u1"].script
    tz = timezone(timedelta(hours=-7))
    run_start = datetime(2026, 5, 2, 10, 30, 41, 500, tzinfo=tz)
    rows = preroll_rows(script, "sim-u1", run_start, 60)
    assert len(rows) == 60
    assert rows[-1].period_ts == datetime(2026, 5, 2, 10, 29, tzinfo=tz)
    assert [b.period_ts - a.period_ts for a, b in zip(rows, rows[1:])] == [timedelta(minutes=1)] * 59
    start = keyframe_sample(script, 0)
    for r in rows:
        assert r.patient_id == "sim-u1" and r.clean_seconds == 60
        for v in SIM_VITALS:
            assert abs(getattr(r, v) - getattr(start, v)) <= _tol(script, v)
    assert rows == preroll_rows(script, "sim-u1", run_start, 60)
