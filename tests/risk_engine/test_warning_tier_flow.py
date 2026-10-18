"""Warning-tier I5 through the engine: ranges, classification, NEWS2, baseline rebase and alerts."""
from datetime import timedelta

from backend.contracts import Adjustment, ContextAdjustments, LiveWindow
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine
from tests.risk_engine.risk_helpers import T0, ctx, period

DRAFT = ContextAdjustments(patient_id="p", adjustments=[
    Adjustment(rule_id="draft:D57", vital="hr", bound="high", value=85, tier="warning")])


def engine(i5=DRAFT):
    e = RiskEngine()
    e.on_intake(ctx(), i5)
    return e


def hr_level(e, hr, minute=0):
    return e.on_period(period(minute, hr=hr, rr=16)).vital_levels.hr


def steady(e, minutes, hr_for, step=0.5):
    for i in range(int(minutes / step)):
        e.on_period(period(i * step, hr=hr_for(i), rr=16))


def test_intake_narrows_the_safe_edge_and_keeps_the_danger_edge():
    hr = engine().ranges["p"].hr
    assert (hr.safe_low, hr.safe_high, hr.danger_low, hr.danger_high) == (51, 85, 40, 131)
    assert any("unreviewed" in r for r in hr.reasons)


def test_a_reading_between_the_new_and_old_edge_becomes_warning():
    assert hr_level(engine(None), 88) == "safe"
    assert hr_level(engine(), 88) == "warning"
    assert hr_level(engine(), 85) == "safe"


def test_danger_still_starts_at_the_original_edge():
    e = engine()
    assert hr_level(e, 130) == "warning"
    assert hr_level(e, 131) == "danger"
    assert hr_level(e, 135) == "danger"


def test_a_draft_does_not_change_news2_points():
    plain, drafted = engine(None), engine()
    for hr in (88, 95, 110):
        w = LiveWindow(patient_id="p", window_end_ts=T0, hr=hr, resp_rate=16, spo2=98, temp_c=37.0)
        assert drafted.on_second(w).news2_points == plain.on_second(w).news2_points
    assert drafted.on_second(w.model_copy(update={"hr": 88})).news2_points.hr == 0


def test_rebase_keeps_learned_samples_and_never_widens_the_drafted_edge():
    e = RiskEngine()
    e.on_intake(ctx())  # first intake has no draft
    steady(e, 35, lambda i: 78 + i % 3)
    samples = len(e.baselines["p"].vitals["hr"].samples)
    assert e.ranges["p"].hr.safe_high > 85  # learned band is wider than the draft allows

    e.on_intake(ctx(), DRAFT)
    hr = e.ranges["p"].hr
    assert len(e.baselines["p"].vitals["hr"].samples) == samples  # learning is kept
    assert hr.source == "personal" and hr.safe_high == 85  # refit is cut at the drafted edge
    assert hr.danger_high == 131

    e.on_intake(ctx(), DRAFT)  # same I5 again
    assert e.ranges["p"].hr == hr


def test_a_draft_cannot_be_widened_by_the_personal_baseline_during_learning():
    e = engine()
    steady(e, 35, lambda i: 78 + i % 3)
    hr = e.ranges["p"].hr
    assert hr.source == "personal" and hr.safe_high == 85 and hr.safe_low > 51


def test_warning_alert_fires_only_after_the_configured_window():
    e = engine()
    logic = AlertLogic(e.config.alerts)
    window = int(e.config.alerts.warning_persisted_minutes)  # 10
    alerts = []
    for minute in range(window + 1):
        alerts.append(logic.on_risk(e.on_period(period(minute, hr=88, rr=16))))
    assert all(a == [] for a in alerts[:window])
    (alert,) = alerts[window]
    assert (alert.trigger, alert.severity, alert.vital) == ("warning_persisted", "warning", "hr")
    assert alert.ts == T0 + timedelta(minutes=window)


def test_same_readings_without_the_draft_raise_no_alert():
    e = engine(None)
    logic = AlertLogic(e.config.alerts)
    assert not any(logic.on_risk(e.on_period(period(m, hr=88, rr=16))) for m in range(15))


def test_known_gap_resting_level_beyond_the_drafted_edge_stays_in_warning():
    """Characterization, not a fix: the baseline skips learning when the patient's own level is outside
    the (drafted) safe band, so a patient who rests at 88 bpm against an edge of 85 is in warning for good."""
    e = engine()
    steady(e, 35, lambda i: 88)
    base = e.baselines["p"].vitals["hr"]
    assert base.status == "skipped" and "own level outside the typical range" in base.why
    hr = e.ranges["p"].hr
    assert (hr.source, hr.safe_high, hr.danger_high) == ("population", 85, 131)
    assert hr_level(e, 88, minute=40) == "warning"
