import numpy as np
import pytest

from receiver.breathing import BreathingEstimator
from tests.receiver.synth import drop_beats, feed, make_beats

WINDOW = 60


def settled(bpm, seed=1, duration=120, **kw):
    """Estimates over the last 20 s after the window has filled."""
    times, rr = make_beats(duration, bpm, seed=seed, **kw)
    return feed(BreathingEstimator(), times, rr, 0, duration)[-20:]


@pytest.mark.parametrize("bpm", [6, 15, 25])
def test_recovers_known_rate(bpm):
    out = settled(bpm)
    values = [v for _, v in out]
    assert all(v is not None and abs(v - bpm) <= 1.0 for v in values)


def test_skipped_and_ectopic_beats_do_not_break_result():
    out = settled(15, n_ectopic=6, n_skipped=4)
    assert all(v is not None and abs(v - 15) <= 1.0 for _, v in out)


def test_no_value_without_contact():
    est = BreathingEstimator()
    times, rr = make_beats(90, 15, seed=1)
    feed(est, times, rr, 0, 90)
    assert est.estimate(90, contact=False) is None
    assert est.last_reason == "no_contact"


def test_no_value_with_too_few_beats():
    est = BreathingEstimator()
    times, rr = make_beats(90, 15, seed=1)
    m = times > 80
    est.add_beats(times[m].tolist(), rr[m].tolist())
    assert est.estimate(90) is None
    assert est.last_reason == "few_beats"


def test_empty_and_odd_input_never_raises():
    est = BreathingEstimator()
    assert est.estimate(10) is None
    est.add_beats([], [])
    est.add_beats([1.0], [800.0])
    assert est.estimate(1.0) is None


def test_no_value_on_noise_without_breathing_signal():
    late = []
    for seed in range(6):
        times, rr = make_beats(240, 15, amp=0, jitter=25, drift=0, n_ectopic=0, seed=seed)
        out = feed(BreathingEstimator(), times, rr, 0, 240)
        late += [v for now, v in out if now >= WINDOW]
    assert sum(v is None for v in late) >= 0.9 * len(late)


def test_short_gap_is_tolerated_and_long_gap_gives_none():
    times, rr = make_beats(150, 15, seed=1)
    for gap, expect_value in [(3, True), (6, False)]:
        t, r = drop_beats(times, rr, 100, 100 + gap)
        est = BreathingEstimator()
        out = dict(feed(est, t, r, 0, 130))
        if expect_value:
            assert abs(out[130] - 15) <= 1.0
        else:
            assert out[130] is None
            assert est.last_reason == "gap"


def test_reset_forgets_everything():
    est = BreathingEstimator()
    times, rr = make_beats(120, 15, seed=1)
    assert feed(est, times, rr, 0, 120)[-1][1] is not None
    est.reset()
    assert est.estimate(120) is None
    assert est.last_reason == "few_beats"


def test_rate_step_never_reports_a_misleading_in_between_value():
    old, new = 8, 22
    times, rr = make_beats(240, lambda t: old if t < 120 else new, seed=2)
    out = feed(BreathingEstimator(), times, rr, 0, 240)
    for now, v in out:
        if now >= 100 and v is not None:
            assert min(abs(v - old), abs(v - new)) <= 2.0, (now, v)
    assert abs(out[-1][1] - new) <= 1.0


def test_old_beats_are_dropped():
    est = BreathingEstimator()
    times, rr = make_beats(600, 15, seed=1)
    feed(est, times, rr, 0, 600)
    # one beat per second at 60 bpm would be 60 in a window; allow generous slack
    assert len(est._times) < 2 * WINDOW * 2
