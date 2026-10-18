import math

import numpy as np

from backend.risk_engine import fast_features as ff


def series(n, hr=75.0, rr=16.0, sp=97.0, step=1.0):
    t = [i * step for i in range(n)]
    return {"hr": (t, [hr + 0.0] * n), "resp_rate": (t, [rr] * n), "spo2": (t, [sp] * n)}, t[-1]


def test_all_features_present_and_window_fill():
    s, now = series(15)
    f = ff.compute_features(s, now)
    assert set(f) == set(ff.FEATURE_NAMES)
    assert math.isfinite(f["spo2_15_med"]) and math.isnan(f["spo2_30_med"])   # 30-min window unfilled at 15 min
    s, now = series(35)
    assert math.isfinite(ff.compute_features(s, now)["spo2_30_med"])


def test_distance_slope_and_spread():
    t = list(range(20))
    sp = [97 - 0.5 * i for i in range(20)]
    f = ff.compute_features({"hr": (t, [70] * 20), "resp_rate": (t, [16] * 20), "spo2": (t, sp)}, 19)
    assert abs(f["spo2_15_slope"] - (-0.5)) < 1e-9
    assert abs(f["spo2_5_dlow"] - (np.median(sp[-5:]) - 91)) < 1e-9
    assert f["hr_5_dhigh"] == 131 - 70 and f["hr_5_dlow"] == 70 - 40 and "spo2_5_dhigh" not in f
    assert f["hr_5_spread"] == 0.0


def test_timestamp_windows_not_row_counts():
    # 5-minute-spaced rows: a 5-minute window holds 1 row -> unfilled; a 30-minute window holds 6 of 30 -> unfilled
    t = [i * 5.0 for i in range(20)]
    f = ff.compute_features({"hr": (t, [70] * 20)}, t[-1])
    assert math.isnan(f["hr_5_med"]) and math.isnan(f["hr_30_med"])


def test_nulls_and_future_points_ignored():
    t = list(range(40))
    vals = [70.0 if i % 3 else None for i in range(40)]
    f = ff.compute_features({"hr": (t, vals)}, 25)
    assert math.isfinite(f["hr_15_med"]) and math.isnan(f["hr_30_med"])  # about 17 of 26 observed -> <18 needed in 30
    assert f["hr_15_max"] == 70.0


def test_baseline_scores_rank_closer_higher():
    far, now = series(35)
    near, _ = series(35, sp=92.0)
    f_far, f_near = ff.compute_features(far, now), ff.compute_features(near, now)
    assert ff.distance_score(f_near) > ff.distance_score(f_far)
    t = list(range(35))
    falling = {"hr": (t, [75] * 35), "resp_rate": (t, [16] * 35), "spo2": (t, [97 - 0.4 * i for i in t[:35]])}
    assert ff.extrapolation_score(ff.compute_features(falling, 34)) > ff.extrapolation_score(f_far)
    assert ff.distance_score({}) == -1e9


def test_live_model_matches_training_features():
    """fast_model.predict (live TrendHistory) gives the same score as the training path on the same minutes."""
    from datetime import datetime, timedelta, timezone

    from backend.risk_engine import fast_model
    from backend.risk_engine.trend import Row, TrendHistory
    t0 = datetime(2026, 10, 18, tzinfo=timezone.utc)
    sp = [97 - 0.3 * i for i in range(40)]
    h = TrendHistory()
    for i in range(40):
        h.rows.append(Row(t0 + timedelta(minutes=i), 72.0, 15.0, sp[i]))
    t = list(range(40))
    f = ff.compute_features({"hr": (t, [72.0] * 40), "resp_rate": (t, [15.0] * 40), "spo2": (t, sp)}, 39)
    score, reason = fast_model.predict(h)
    assert score == ff.distance_score(f) and reason == "SpO2 falling"
