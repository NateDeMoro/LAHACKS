from datetime import datetime, timedelta, timezone

import pytest

from backend.simulator.generate import generate, keyframe_sample, preroll_rows
from backend.simulator.models import KEY_FRACTIONS, SIM_VITALS
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


@pytest.mark.parametrize("pid", list(PROFILES))
def test_samples_follow_the_line_and_look_like_a_device(pid):
    script = PROFILES[pid].script
    n = 600
    out = generate(script, n)
    glitched = {(g.vital, i) for g in script.glitches
                for i in range(round(g.at * (n - 1)), round(g.at * (n - 1)) + g.duration_s)}
    for i, s in enumerate(out):
        line = keyframe_sample(script, i / (n - 1))
        for v in SIM_VITALS:
            if (v, i) in glitched:
                continue
            assert abs(getattr(s, v) - getattr(line, v)) <= _tol(script, v), (v, i)
        assert float(s.hr).is_integer() and float(s.resp_rate).is_integer() and float(s.spo2).is_integer()
        assert s.spo2 <= 100
        assert s.temp_c == round(s.temp_c, 1)
    for s, at in ((out[0], 0.0), (out[-1], 1.0)):
        for v in SIM_VITALS:
            assert abs(getattr(s, v) - getattr(keyframe_sample(script, at), v)) <= _tol(script, v)


@pytest.mark.parametrize("n", LENGTHS)
def test_key_fraction_scales_with_length(n):
    script = PROFILES["c2"].script  # steep hr slope, so a mis-scaled index would show
    out = generate(script, n)
    i = round(0.6 * (n - 1))
    assert abs(out[i].hr - keyframe_sample(script, 0.6).hr) <= _tol(script, "hr") + 0.5


def test_h1_spo2_glitch_is_exact():
    script = PROFILES["h1"].script
    n = 600
    start = round(0.5 * (n - 1))
    hits = [i for i, s in enumerate(generate(script, n)) if s.spo2 == 90]
    assert hits == list(range(start, start + 8))


def test_preroll_rows():
    script = PROFILES["u1"].script
    tz = timezone(timedelta(hours=-7))
    run_start = datetime(2026, 5, 2, 10, 30, 41, 500, tzinfo=tz)
    rows = preroll_rows(script, "sim-u1", run_start, 60)
    assert len(rows) == 60
    assert rows[-1].minute_ts == datetime(2026, 5, 2, 10, 29, tzinfo=tz)
    assert [b.minute_ts - a.minute_ts for a, b in zip(rows, rows[1:])] == [timedelta(minutes=1)] * 59
    start = keyframe_sample(script, 0)
    for r in rows:
        assert r.patient_id == "sim-u1" and r.clean_seconds == 60
        for v in SIM_VITALS:
            assert abs(getattr(r, v) - getattr(start, v)) <= _tol(script, v)
    assert rows == preroll_rows(script, "sim-u1", run_start, 60)
