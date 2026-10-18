import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

lgb = pytest.importorskip("lightgbm")

from backend.contracts import PeriodSummary
from backend.risk_engine import fast_features as ff
from backend.risk_engine import fast_model
from backend.risk_engine.trend import TrendHistory
from training import fast_forecast as fc
from training.mimic_numerics import Segment


def test_window_boundaries():
    x = np.arange(40, dtype=float)
    lo, hi = fc.window_extreme(x, "low"), fc.window_extreme(x, "high")
    assert lo[0] == 1 and hi[0] == 15            # minutes 1..15, current minute excluded
    assert lo[24] == 25 and hi[24] == 39         # last row with a full window
    assert np.isnan(lo[25:]).all()               # window would run past the segment


def test_too_few_observed_is_skipped():
    x = np.full(40, 95.0)
    x[1:5] = np.nan                              # row 0: minutes 1..15 have 11 observed (< 12)
    x[8] = 80.0
    out = fc.window_extreme(x, "low")
    assert np.isnan(out[0])
    assert out[1] == 80.0                        # row 1: minutes 2..16 have 12 observed
    x[5] = np.nan                                # row 1 drops to 11 observed
    assert np.isnan(fc.window_extreme(x, "low")[1])


def test_extreme_ignores_missing_values():
    x = np.full(30, 97.0)
    x[6] = np.nan
    x[10] = 88.0
    assert fc.window_extreme(x, "low")[0] == 88.0 and fc.window_extreme(x, "high")[0] == 97.0


def test_short_array_and_build_targets():
    assert np.isnan(fc.window_extreme(np.ones(10), "low")).all()
    n = 60
    seg = Segment("p", "r", "1min", 0, np.full(n, 75.0), np.full(n, 16.0), np.linspace(98, 90, n), np.full(n, np.nan))
    t = fc.build_targets(seg)
    assert set(t) == {name for name, *_ in fc.TARGETS}
    assert t["spo2_low"][0] == pytest.approx(seg.spo2[15]) and t["hr_high"][0] == 75.0


def _boosters(seed=0):
    """Tiny random-data cautious/median models on the real feature names (stand-ins for the trained ones)."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(400, len(ff.FEATURE_NAMES))), columns=ff.FEATURE_NAMES)
    out = {}
    for name, *_ in fc.TARGETS:
        y = -2 * X["spo2_15_slope"].to_numpy() + rng.normal(size=len(X))
        for tag in ("median", "cautious"):
            out[(name, tag)] = lgb.train(dict(objective="quantile", alpha=0.5, verbose=-1, num_leaves=4, num_threads=1),
                                         lgb.Dataset(X, y), num_boost_round=5)
    return out


def _install(tmp_path, monkeypatch, boosters):
    targets = []
    for name, vital, kind, alpha in fc.TARGETS:
        boosters[(name, "cautious")].save_model(str(tmp_path / f"{name}.txt"))
        targets.append(dict(name=name, vital=vital, kind=kind, cautious_file=f"{name}.txt"))
    (tmp_path / "bundle.json").write_text(json.dumps(dict(features=ff.FEATURE_NAMES, targets=targets)))
    monkeypatch.setattr(fast_model, "METHOD", "forecast")
    monkeypatch.setattr(fast_model, "MODELS", tmp_path)
    monkeypatch.setattr(fast_model, "FORECAST_PATH", tmp_path / "bundle.json")
    assert fast_model.load()


def _history(spo2, hr=75.0, rr=16.0):
    h = TrendHistory()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for k, s in enumerate(spo2):
        h.add(PeriodSummary(patient_id="p", period_ts=base + timedelta(minutes=k), hr=hr, resp_rate=rr, spo2=s,
                            temp_c=36.8, clean_seconds=60))
    return h


def test_forecast_method_scores_a_falling_spo2_higher(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, _boosters())
    falling = fast_model.predict(_history(list(np.linspace(97, 92, 25))))
    flat = fast_model.predict(_history([97.0] * 25))
    assert falling is not None and flat is not None
    assert falling[0] > flat[0]
    assert "within 15 min" in falling[1] and "may reach" in falling[1]


def test_train_serve_parity(tmp_path, monkeypatch):
    """The score from the live path (TrendHistory -> fast_model.predict) equals the training path
    (segment_rows features -> predict_frame -> score_from) on the same minutes, with missing values."""
    boosters = _boosters()
    _install(tmp_path, monkeypatch, boosters)
    rng = np.random.default_rng(1)
    n = 80
    spo2 = np.round(np.linspace(98, 92, n) + rng.normal(0, 0.5, n))
    spo2[[20, 21, 50]] = np.nan
    hr = np.round(75 + rng.normal(0, 3, n))
    seg = Segment("p", "r", "1min", 0, hr, np.full(n, 16.0), spo2, np.full(n, np.nan))
    _, recs, _, _, _ = fc.tf.segment_rows((0, seg))
    df = pd.DataFrame(recs)
    _, cau = fc.predict_frame(boosters, df)
    train_scores = dict(zip(df.i, fc.score_from(cau)))
    for i in (30, 45, 70):
        h = TrendHistory()
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for k in range(i + 1):
            h.add(PeriodSummary(patient_id="p", period_ts=base + timedelta(minutes=k), hr=float(hr[k]), resp_rate=16.0,
                                spo2=None if np.isnan(spo2[k]) else float(spo2[k]), temp_c=36.8, clean_seconds=60))
        live = fast_model.predict(h)[0]
        assert live == pytest.approx(train_scores[i], abs=1e-6)


def test_capped_warning():
    from training.train_fast import event_warnings
    assert event_warnings([60], 100) == (40, None)       # alert at -40: caught uncapped only
    assert event_warnings([90], 100) == (10, 10)         # alert at -10: caught, warning 10
    assert event_warnings([60, 85], 100) == (40, 15)     # stale early alert ignored by the capped window
    assert event_warnings([], 100) == (None, None)
