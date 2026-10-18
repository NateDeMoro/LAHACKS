from collections import Counter

import numpy as np
import pytest

from training import mimic_numerics as mn
from training.mimic_numerics import Segment


def test_name_mapping_and_duplicate_merge():
    names = ["Hr", "PULSE", "resp", "%SpO2", "NBP Sys", "RESP ", "ABPSys"]
    sig = np.array([[np.nan, 80, 14, 97, 120, 15, 100]] * 3, dtype=float)
    ch = mn.map_signals(names, sig)
    assert set(ch) == {"hr", "resp_rate", "spo2", "sbp"}      # ABPSys is ignored
    assert len(ch["resp_rate"]) == 2          # RESP and "RESP " merge
    assert len(ch["hr"]) == 2 and np.isnan(ch["hr"][0][0]) and ch["hr"][1][0] == 80   # HR first, PULSE second


def test_pulse_only_fills_where_hr_missing_and_limits_apply():
    hr = np.array([70, 0, np.nan, 300], float)
    pulse = np.array([71, 72, 73, 74], float)
    out = mn.to_minutes({"hr": [hr, pulse]}, 1)["hr"]
    assert list(out) == [70, 72, 73, 74]       # 0 and 300 are outside limits; PULSE fills them


def test_one_hz_collapses_to_minute_median():
    x = np.concatenate([np.full(60, 80.0), np.r_[np.full(29, 90.0), np.full(31, np.nan)], np.full(60, 70.0)])
    x[5] = 200.0                                # one outlier second inside the first minute (inside limits)
    out = mn.to_minutes({"hr": [x]}, 60)["hr"]
    assert out[0] == 80.0 and np.isnan(out[1]) and out[2] == 70.0   # minute 1 has only 29 samples: dropped


def test_spo2_artifact_filter():
    x = np.array([97, 96, 80, 79, 96, 96], float)       # 2-minute probe dropout
    out = mn.spo2_artifact_filter(x, Counter())
    assert np.isnan(out[2]) and np.isnan(out[3]) and out[4] == 96
    sustained = np.array([97] + [80] * 8, float)        # real, sustained fall is kept after 4 rejections
    out = mn.spo2_artifact_filter(sustained)
    assert np.isnan(out[1:5]).all() and (out[5:] == 80).all()
    slow = np.array([97, 92, 87, 82, 77], float)        # 5-point steps are not artifacts
    assert (mn.spo2_artifact_filter(slow) == slow).all()


def _seg(hr, rr, sp, n=None):
    n = n or len(hr)
    return Segment("p1", "r1", "1min", 0, np.asarray(hr, float), np.asarray(rr, float), np.asarray(sp, float),
                   np.full(n, np.nan))


def test_neonate_filter():
    n = 120
    adult = _seg(np.full(n, 75), np.full(n, 16), np.full(n, 97))
    neonate_hr = _seg(np.full(n, 140), np.full(n, 20), np.full(n, 97))
    neonate_rr = _seg(np.full(n, 75), np.full(n, 40), np.full(n, 97))
    danger = _seg(np.full(n, 75), np.full(n, 16), np.r_[np.full(40, 97), np.full(80, 85)])  # 67% in danger
    assert not mn.is_neonate(adult)
    assert mn.is_neonate(neonate_hr) and mn.is_neonate(neonate_rr) and mn.is_neonate(danger)


def test_split_segments_on_gaps():
    a = np.r_[np.full(60, 75.0), np.full(15, np.nan), np.full(60, 75.0)]
    mins = {"hr": a, "resp_rate": a * 0 + 16, "spo2": a * 0 + 97}
    c = Counter()
    segs = mn.split_segments(mins, "p", "r", "1min", c)
    assert len(segs) == 2 and segs[1].start == 75 and c["gap_splits"] == 1
    small = {k: v[:30] for k, v in mins.items()}
    assert mn.split_segments(small, "p", "r", "1min", Counter()) == []


def test_read_record_end_to_end(tmp_path):
    wfdb = pytest.importorskip("wfdb")
    n = 180                                      # 3 minutes at 1 Hz per row -> use 1/60 Hz record of 180 minutes
    sig = np.column_stack([np.full(n, 75.0), np.full(n, 80.0), np.full(n, 15.0), np.full(n, 97.0)])
    wfdb.wrsamp("p000001-2100-01-01-00-00n", fs=1 / 60, units=["bpm", "bpm", "pm", "%"],
                sig_name=["HR", "PULSE", "RESP", "SpO2"], p_signal=sig, fmt=["16"] * 4, adc_gain=[10] * 4,
                baseline=[0] * 4, write_dir=str(tmp_path))
    c = Counter()
    segs = mn.read_record(tmp_path / "p000001-2100-01-01-00-00n.hea", c)
    assert len(segs) == 1 and segs[0].rate == "1min" and len(segs[0]) == n
    assert np.nanmedian(segs[0].hr) == 75.0      # HR wins over PULSE
