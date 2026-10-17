from backend.contracts import RangesFile
from backend.risk_engine import ranges

from risk_helpers import ctx


def test_no_context_or_file_gives_plain_news2_bands():
    r = ranges.build_population_ranges(None, None)
    assert (r.hr.safe_low, r.hr.safe_high, r.hr.danger_low, r.hr.danger_high) == (51, 90, 40, 131)
    assert r.spo2.danger_high is None and r.temp_c.danger_high is None


def test_safe_band_is_inside_news2_score0_and_danger(rf):
    r = ranges.build_population_ranges(ctx(), rf)
    for v in ("hr", "sbp", "resp_rate", "spo2", "temp_c"):
        rng, (s_lo, s_hi) = getattr(r, v), ranges.SCORE0[v]
        assert s_lo <= rng.safe_low < rng.safe_high <= s_hi
        assert rng.danger_low < rng.safe_low
        assert rng.danger_high is None or rng.safe_high < rng.danger_high


def test_fit_narrower_than_score0_tightens_the_band(rf):
    r = ranges.build_population_ranges(ctx(), rf)
    assert r.sbp.safe_high == 150  # fitted 97.5th is below the NEWS2 219
    assert r.sbp.safe_low == 111   # fitted 100 is below NEWS2 111, so score-0 wins


def test_fit_wider_than_score0_cannot_loosen_the_band(rf):
    r = ranges.build_population_ranges(ctx(), rf)
    assert (r.hr.safe_low, r.hr.safe_high) == (51, 90)


def test_too_narrow_intersection_falls_back_to_score0(rf):
    rf.targets["hr"].q025.intercept, rf.targets["hr"].q975.intercept = 80, 85
    r = ranges.build_population_ranges(ctx(), rf)
    assert (r.hr.safe_low, r.hr.safe_high) == (51, 90)
    assert any("too narrow" in x for x in r.hr.reasons)


def test_quantiles_never_cross(rf):
    rf.targets["hr"].q025.intercept, rf.targets["hr"].q975.intercept = 100, 40  # swapped
    r = ranges.build_population_ranges(ctx(), rf)
    assert r.hr.safe_low < r.hr.safe_high


def test_beta_blocker_gets_a_lower_typical_value_reason(rf):
    r = ranges.build_population_ranges(ctx(drug_classes=["beta_blocker"]), rf)
    assert any("heart rate 6 bpm lower: beta-blocker" in x for x in r.hr.reasons)
    assert not ranges.build_population_ranges(ctx(), rf).hr.reasons


def test_missing_fields_fall_back_with_a_reason(rf):
    c = ctx().model_copy(update={"age": None, "height_cm": None, "weight_kg": None, "sex": None})
    r = ranges.build_population_ranges(c, rf)
    notes = " ".join(r.hr.reasons)
    assert "age missing" in notes and "BMI missing" in notes and "sex missing" in notes


def test_out_of_range_age_and_bmi_are_clamped(rf):
    feats, _ = ranges.features_from_context(ctx().model_copy(update={"age": 95, "weight_kg": 200}), rf)
    assert feats["age"] == 80 and feats["bmi"] == 50


def test_temperature_band_shifts_with_age(rf):
    old = ranges.build_population_ranges(ctx().model_copy(update={"age": 80}), rf).temp_c
    young = ranges.build_population_ranges(ctx().model_copy(update={"age": 20}), rf).temp_c
    assert old.safe_high < young.safe_high


def test_pregnancy_is_flagged_not_modelled(rf):
    r = ranges.build_population_ranges(ctx(pregnant=True), rf)
    assert any("pregnancy not modelled" in x for x in r.hr.reasons)


def test_clamp_keeps_safe_inside_danger():
    assert ranges.clamp_safe("hr", 30, 200) == (41, 130)
    assert ranges.clamp_safe("temp_c", 34, None) == (35.1, None)


def test_centres_hr_is_the_clipped_median(rf):
    assert ranges.population_centres(ctx(drug_classes=["beta_blocker"]), rf)["hr"] < \
        ranges.population_centres(ctx(), rf)["hr"]
    assert 51 <= ranges.population_centres(ctx(), rf)["hr"] <= 90
    assert ranges.population_centres(None, rf) == {"resp_rate": 16.0, "hr": 70.0}
