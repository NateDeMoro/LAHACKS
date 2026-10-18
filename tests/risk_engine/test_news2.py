import math

import pytest

from backend.contracts import LiveWindow, PeriodSummary
from backend.risk_engine import news2


@pytest.mark.parametrize("fn,cases", [
    (news2.score_rr, [(8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (20.5, 2), (21, 2), (24, 2), (25, 3)]),
    (news2.score_spo2, [(91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0)]),
    (news2.score_sbp, [(90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3)]),
    (news2.score_hr, [(40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3)]),
    (news2.score_temp, [(35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1), (39.0, 1), (39.1, 2)]),
])
def test_band_edges(fn, cases):
    for value, points in cases:
        assert fn(value) == points, (fn.__name__, value)


def test_all_normal_scores_zero():
    total, pts = news2.score(resp_rate=16, spo2=98, on_oxygen=False, sbp=120, hr=70,
                             alertness="alert", temp_c=37.0)
    assert total == 0 and pts.on_oxygen == 0


def test_worst_case_scores_twenty():
    total, _ = news2.score(resp_rate=25, spo2=91, on_oxygen=True, sbp=90, hr=131,
                           alertness="new_confusion", temp_c=35.0)
    assert total == 20


def test_half_up_rounding():
    assert news2.score_rr(20.5) == 2  # 21, not banker's 20
    assert news2.score_rr(24.5) == 3  # 25, not banker's 24


def test_null_vital_gets_null_points_and_is_left_out():
    total, pts = news2.score(resp_rate=21, spo2=None, hr=70)
    assert pts.spo2 is None and total == 2
    assert news2.score()[0] is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_is_treated_as_null(bad):
    total, pts = news2.score(resp_rate=bad, hr=bad, temp_c=bad, spo2=bad, sbp=bad)
    assert total is None and pts.hr is None and pts.temp_c is None


@pytest.mark.parametrize("model,field", [(PeriodSummary, "hr"), (LiveWindow, "resp_rate")])
def test_contract_rejects_nan_and_infinity(model, field):
    for bad in (math.nan, math.inf):
        with pytest.raises(ValueError):
            model(**{field: bad})


def test_raw_eicu_row_scores_as_the_chart_does():
    # eICU stay 197617, offset 4064, scored by hand from the NEWS2 chart: HR 117 -> 2, RR 48 -> 3,
    # SpO2 93 -> 2, temp 37.7 -> 0
    _, pts = news2.score(hr=117, resp_rate=48, spo2=93, temp_c=37.7)
    assert (pts.hr, pts.resp_rate, pts.spo2, pts.temp_c) == (2, 3, 2, 0)
