import random

import pytest

from backend.contracts import BaselineConfig
from backend.risk_engine.baseline import PersonalBaseline
from backend.risk_engine.engine import RiskEngine
from risk_helpers import ctx, minute


def feed(base, hrs, rrs=None, start=0, step=1):
    for i, hr in enumerate(hrs):
        base.update(minute(start + i * step, hr=hr, rr=None if rrs is None else rrs[i]))


def steady(level, n, sd=1.0, seed=0):
    rnd = random.Random(seed)
    return [level + rnd.gauss(0, sd) for _ in range(n)]


def make(cfg, pop, mu0=70.0):
    return PersonalBaseline(cfg, pop, {"hr": mu0, "resp_rate": 16.0})


def test_nothing_changes_before_the_minimum_minutes(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(75, 9))
    assert b.ranges.hr.source == "population"


def test_steady_patient_gets_a_narrower_band_containing_their_level(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(85, 20))
    hr = b.ranges.hr
    assert hr.source == "personal" and hr.safe_low <= 85 <= hr.safe_high
    assert hr.safe_high - hr.safe_low < pop.hr.safe_high - pop.hr.safe_low
    assert any("narrowed to your readings" in r for r in hr.reasons)


def test_band_never_wider_than_or_outside_population(cfg, pop):
    for level in (55, 70, 88):
        b = make(cfg, pop)
        feed(b, steady(level, 40, sd=3))
        hr = b.ranges.hr
        assert pop.hr.safe_low <= hr.safe_low and hr.safe_high <= pop.hr.safe_high


def test_danger_edges_never_move(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(75, 40))
    assert (b.ranges.hr.danger_low, b.ranges.hr.danger_high) == (40, 131)


def test_prior_weight_follows_the_variance_ratio(cfg, pop):
    # a very steady patient trusts their own data (n0 at its floor): the band centres on their level
    b = make(cfg, pop, mu0=60)
    feed(b, steady(80, 12, sd=0.1))
    assert abs((b.ranges.hr.safe_low + b.ranges.hr.safe_high) / 2 - 80) < 2


def test_spread_floor_and_min_width_hold_on_a_flat_signal(cfg, pop):
    b = make(cfg, pop)
    feed(b, [75.0] * 15)
    hr = b.ranges.hr
    assert hr.safe_high - hr.safe_low >= cfg.min_width["hr"] - 0.1


def test_abnormal_on_arrival_is_skipped_per_vital(cfg, pop):
    # with the starting RR floor of 2 the band (about 10 wide) is wider than 12-20, so breathing would
    # never narrow; a floor of 1 stands in for the tuned value
    cfg = cfg.model_copy(update={"spread_floor": {"hr": 5, "resp_rate": 1}})
    b = make(cfg, pop)
    feed(b, [95.0] + steady(95, 20), rrs=[16.0] * 21)  # HR 95 scores 1; breathing is fine
    assert b.ranges.hr.source == "population"
    assert "abnormal on arrival" in " ".join(b.ranges.hr.reasons)
    assert b.ranges.resp_rate.source == "personal"


def test_a_mildly_high_but_scoreless_arrival_still_learns(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(88, 20, sd=0.5))
    assert b.ranges.hr.source == "personal"


def test_abnormal_after_the_arrival_window_does_not_skip(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(75, 5) + [95.0] + steady(75, 15))
    assert "abnormal on arrival" not in " ".join(b.ranges.hr.reasons)


def test_own_level_outside_the_population_band_is_not_personalized(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(75, 5) + steady(100, 20, sd=0.5))  # median ends above 90
    assert b.ranges.hr.source == "population"


def test_band_freezes_after_the_learning_window(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(72, 31, sd=1))
    frozen = b.ranges.hr.model_copy()
    feed(b, steady(86, 30, sd=1), start=31)  # a slow drift upward after the window
    assert b.ranges.hr == frozen


def test_windows_count_time_not_rows(cfg, pop):
    five_min = make(cfg, pop)
    feed(five_min, steady(75, 4), step=5)  # 15 minutes of data in 4 rows
    assert five_min.ranges.hr.source == "personal"
    short = make(cfg, pop)
    feed(short, steady(75, 4), step=1)  # 3 minutes in 4 rows
    assert short.ranges.hr.source == "population"


def test_dirty_minutes_are_ignored(cfg, pop):
    b = make(cfg, pop)
    for i, hr in enumerate(steady(75, 20)):
        b.update(minute(i, hr=hr, clean=10))
    assert b.ranges.hr.source == "population"


def test_other_vitals_are_never_personalized(cfg, pop):
    b = make(cfg, pop)
    feed(b, steady(75, 40))
    r = b.ranges
    assert r.spo2 == pop.spo2 and r.temp_c == pop.temp_c and r.sbp == pop.sbp


def test_engine_flags_a_drift_inside_the_population_band(cfg):
    eng = RiskEngine()
    eng.on_intake(ctx(drug_classes=[]))
    seen = []
    eng.ranges_listener = seen.append
    for i, hr in enumerate(steady(70, 31, sd=1)):
        eng.on_minute(minute(i, hr=hr))
    assert seen and eng.ranges["p"].hr.source == "personal"
    assert eng.on_minute(minute(40, hr=86)).level == "warning"  # inside 51-90, outside the personal band
    assert eng.intake_ranges["p"].hr.source == "population"      # the simulator's copy never narrows


def test_engine_without_intake_uses_plain_news2_bands():
    eng = RiskEngine()
    res = eng.on_minute(minute(0, hr=95, pid="eicu-1"))
    assert res.level == "warning" and eng.ranges["eicu-1"].hr.safe_high == 90


def test_engine_classifies_with_news2_rounding():
    eng = RiskEngine()
    assert eng.on_minute(minute(0, rr=20.4, pid="x")).level == "safe"   # rounds to 20
    assert eng.on_minute(minute(1, rr=20.5, pid="x")).level == "warning"  # rounds to 21
