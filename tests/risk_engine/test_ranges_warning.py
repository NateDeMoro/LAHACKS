"""Warning-tier I5 adjustments (drafted rules): narrow the safe edge only, never the danger edge."""
import pytest

from backend.contracts import Adjustment, ContextAdjustments
from backend.risk_engine.ranges import apply_i5, score0_ranges

POP = score0_ranges("p")  # hr 51-90 (danger 40/131), resp 12-20, spo2 96-100, temp 36.1-38.0


def warn(vital, bound, value, rule_id="draft:D57"):
    return Adjustment(rule_id=rule_id, vital=vital, bound=bound, value=value, tier="warning")


def danger(vital, bound, value, rule_id="chemo_fever", tier=None):
    return Adjustment(rule_id=rule_id, vital=vital, bound=bound, value=value, tier=tier)


def apply(*adjs, pop=POP):
    return apply_i5(pop, ContextAdjustments(patient_id="p", adjustments=list(adjs)))


def test_high_bound_narrows_the_safe_high_edge_only():
    hr = apply(warn("hr", "high", 85)).hr
    assert (hr.safe_low, hr.safe_high) == (51, 85)
    assert (hr.danger_low, hr.danger_high) == (40, 131)


def test_low_bound_narrows_the_safe_low_edge_only():
    hr = apply(warn("hr", "low", 60)).hr
    assert (hr.safe_low, hr.safe_high) == (60, 90)
    assert (hr.danger_low, hr.danger_high) == (40, 131)


def test_works_for_every_graded_vital():
    r = apply(warn("resp_rate", "high", 17), warn("spo2", "low", 97), warn("temp_c", "high", 37.4))
    assert r.resp_rate.safe_high == 17 and r.resp_rate.danger_high == 25
    assert r.spo2.safe_low == 97 and r.spo2.danger_low == 91
    assert r.temp_c.safe_high == 37.4 and r.temp_c.danger_high is None


@pytest.mark.parametrize("adj", [
    warn("hr", "high", 90),            # equal to the current edge
    warn("hr", "high", 95),            # would loosen
    warn("hr", "low", 51),             # equal
    warn("hr", "low", 45),             # would loosen
    warn("hr", "high", None),          # missing value
    warn("hr", None, 80),              # missing bound
    warn("sbp", "high", 130),          # not graded per period
    warn(None, "high", 80),            # missing vital
])
def test_ignored_adjustments_leave_the_ranges_as_they_were(adj):
    assert apply(adj) == POP


def test_narrow_result_is_ignored_as_a_whole():
    # menu minimum widths: hr 16, resp_rate 4, spo2 2, temp_c 0.6
    for adj in (warn("hr", "high", 60), warn("hr", "low", 80), warn("resp_rate", "high", 15),
                warn("spo2", "low", 99), warn("temp_c", "high", 36.5)):
        assert apply(adj) == POP, adj


def test_exactly_the_minimum_width_is_allowed():
    assert apply(warn("hr", "high", 67)).hr.safe_high == 67
    assert apply(warn("spo2", "low", 98)).spo2.safe_low == 98
    assert apply(warn("temp_c", "high", 36.7)).temp_c.safe_high == 36.7


def test_input_is_not_mutated():
    before = POP.model_copy(deep=True)
    apply(warn("hr", "high", 85))
    assert POP == before


def test_two_on_the_same_edge_keep_the_milder_one():
    for order in ((85, 80), (80, 85)):
        r = apply(*(warn("hr", "high", v, rule_id=f"draft:D{v}") for v in order))
        assert r.hr.safe_high == 85
        assert len(r.hr.reasons) == 1 and "D85" in r.hr.reasons[0]
    for order in ((55, 60), (60, 55)):
        assert apply(*(warn("hr", "low", v) for v in order)).hr.safe_low == 55


def test_both_edges_of_one_vital_can_each_take_a_warning():
    hr = apply(warn("hr", "low", 55), warn("hr", "high", 85)).hr
    assert (hr.safe_low, hr.safe_high) == (55, 85)


def test_reason_line_marks_a_draft_as_unreviewed():
    hr = apply(warn("hr", "high", 85, rule_id="draft:D57")).hr
    assert hr.reasons == ["heart rate warning limit 85: draft (D57), unreviewed"]


def test_danger_tier_reason_line_is_unchanged():
    expected = ["heart rate danger high limit 100: chemo fever"]
    assert apply(danger("hr", "high", 100)).hr.reasons == expected
    assert apply(danger("hr", "high", 100, tier="danger")).hr.reasons == expected


def test_null_and_danger_tier_move_the_danger_edge_as_before():
    for tier in (None, "danger"):
        hr = apply(danger("hr", "high", 100, tier=tier)).hr
        assert (hr.danger_high, hr.safe_high) == (100, 90)


def test_mixed_batch_applies_danger_first_then_warning_inside_the_resulting_band():
    # the warning is listed first but a danger edge at 85 pulls safe_high to 84, so 86 is a no-op
    r = apply(warn("hr", "high", 86), danger("hr", "high", 85))
    assert (r.hr.safe_high, r.hr.danger_high) == (84, 85)
    assert r.hr.reasons == ["heart rate danger high limit 85: chemo fever"]

    r = apply(warn("hr", "high", 70), danger("hr", "high", 85))
    assert (r.hr.safe_high, r.hr.danger_high) == (70, 85)  # the warning never moves the danger edge
    assert [x.split(":")[0] for x in r.hr.reasons] == ["heart rate danger high limit 85",
                                                        "heart rate warning limit 70"]
