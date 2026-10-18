import logging
import sys
from datetime import timedelta

import pytest

from backend.contracts import PeriodSummary
from backend.risk_engine import fast_model
from backend.risk_engine.engine import RiskEngine
from risk_helpers import T0


def row(i, step=1, hr=72, rr=15, spo2=98, clean=60):
    return PeriodSummary(patient_id="p", period_ts=T0 + timedelta(minutes=i * step), hr=hr,
                         resp_rate=rr, spo2=spo2, temp_c=36.8, clean_seconds=clean)


def run(rows):
    eng = RiskEngine()
    return [eng.on_period(r) for r in rows]


@pytest.fixture
def model(monkeypatch):
    """A loaded fast model returning a fixed (score, reason); calls are recorded."""
    state = {"out": (9.0, "SpO2 falling"), "calls": 0}

    def predict(history):
        state["calls"] += 1
        if isinstance(state["out"], Exception):
            raise state["out"]
        return state["out"]

    monkeypatch.setattr(fast_model, "load", lambda: True)
    monkeypatch.setattr(fast_model, "predict", predict)
    return state


def test_starts_after_15_elapsed_minutes(model):
    res = run([row(i) for i in range(17)])
    assert all(r.trend_prob_fast is None for r in res[:15])
    assert res[15].trend_prob_fast == 9.0 and res[15].trend_tier == "warning"


def test_half_minute_rows_reach_the_model_as_one_minute_rows(monkeypatch):
    seen = []
    monkeypatch.setattr(fast_model, "load", lambda: True)
    monkeypatch.setattr(fast_model, "predict", lambda history: seen.append(list(history.rows)))
    run([row(i, step=0.5, hr=70 + 4 * (i % 2)) for i in range(35)])  # 30 s rows: 17 whole minutes and a half
    rows = seen[-1]  # the last minute holds only its first 30 s row
    assert len(rows) == 18
    assert [r.ts for r in rows] == [T0 + timedelta(minutes=k) for k in range(18)]
    assert [r.hr for r in rows[:-1]] == [72] * 17 and rows[-1].hr == 70


def test_a_third_row_in_a_minute_is_kept_apart():
    eng = RiskEngine()
    for sec, hr in ((0, 60), (30, 60), (40, 100)):  # a run restarts the 30 s grid mid-minute
        eng.on_period(row(0, hr=hr).model_copy(update={"period_ts": T0 + timedelta(seconds=sec)}))
    assert [r.hr for r in list(eng.trend.histories["p"].rows)] == [60, 100]


def test_threshold_counts_elapsed_time_not_rows(model):
    res = run([row(i, step=5) for i in range(5)])  # eICU spacing: minute 0, 5, 10, 15, 20
    assert [r.trend_tier for r in res] == [None, None, None, "warning", "warning"]


def test_unclean_minutes_do_not_count(model):
    res = run([row(i, clean=10) for i in range(20)])
    assert all(r.trend_prob_fast is None for r in res)


def test_null_while_a_vital_is_in_danger(model):
    res = run([row(i) for i in range(16)] + [row(16, spo2=90)])
    assert res[-1].level == "danger" and res[-1].trend_prob_fast is None
    assert model["calls"] == 1  # only minute 15


def test_raises_safe_to_warning_with_trend_reason(model):
    r = run([row(i) for i in range(16)])[-1]
    assert r.level == "warning" and r.reason == "SpO2 falling" and r.vital is None


def test_raise_only(model):
    rows = [row(i) for i in range(16)] + [row(16, rr=22)]  # breathing 22 is warning on its own
    r = run(rows)[-1]
    assert r.level == "warning" and r.vital == "resp_rate" and "breathing" in r.reason
    assert r.trend_tier == "warning" and r.trend_reason_fast == "SpO2 falling"


def test_below_cutoff_leaves_level_alone(model):
    model["out"] = (-9.0, "x")  # far below the shipped cutoff (models/config.json)
    r = run([row(i) for i in range(16)])[-1]
    assert r.level == "safe" and r.trend_prob_fast == -9.0 and r.trend_tier is None


def test_shipped_model_calm_patient_gets_score_but_no_tier():
    res = run([row(i) for i in range(20)])
    assert all(r.trend_prob_fast is None for r in res[:15])
    assert all(r.trend_prob_fast is not None and r.trend_tier is None and r.level == "safe" for r in res[15:])


def test_model_returning_none(model):
    model["out"] = None
    res = run([row(i) for i in range(20)])
    assert all(r.trend_prob_fast is None and r.level == "safe" for r in res)


def test_throwing_model_is_logged_once(model, caplog):
    model["out"] = RuntimeError("boom")
    with caplog.at_level(logging.ERROR):
        res = run([row(i) for i in range(20)])
    assert all(r.trend_prob_fast is None and r.level == "safe" for r in res)
    assert len([x for x in caplog.records if "fast trend model failed" in x.message]) == 1


def test_rule_methods_need_no_lightgbm(monkeypatch):
    monkeypatch.setattr(fast_model, "METHOD", "distance")
    monkeypatch.setitem(sys.modules, "lightgbm", None)  # makes `import lightgbm` raise ImportError
    assert fast_model.load() is True
    assert run([row(i) for i in range(20)])[-1].trend_prob_fast is not None


def test_stale_news2_is_nulled():
    from backend.contracts import LiveWindow
    eng = RiskEngine()
    eng.on_second(LiveWindow(patient_id="p", window_end_ts=T0, hr=72, resp_rate=15, spo2=98, temp_c=36.8))
    fresh = eng.on_period(row(0))
    stale = eng.on_period(row(2))  # 120 s after the last I14
    assert fresh.news2 is not None and stale.news2 is None and stale.news2_points is None
