"""Shared models for interfaces I1-I17. Source of truth: notes/component-map.md.

Every field is nullable with default None, unknown fields are rejected, NaN and
infinity are rejected, and timestamps must be timezone-aware.
"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return v


Ts = Annotated[datetime | None, AfterValidator(_aware)]

Sex = Literal["male", "female"]
Condition = Literal["hypertension", "asthma", "cancer", "diabetes", "thyroid", "copd",
                    "liver", "heart_disease", "stroke", "heart_failure"]
Alertness = Literal["alert", "new_confusion", "voice", "pain", "unresponsive"]
Vital = Literal["hr", "resp_rate", "spo2", "temp_c", "sbp"]
Bound = Literal["low", "high"]
Level = Literal["safe", "warning", "danger"]
Severity = Literal["warning", "urgent", "high"]
Trigger = Literal["vital_danger", "news2_total", "warning_persisted", "trend"]
RangeSource = Literal["population", "personal"]
TrendTier = Literal["warning"]
RunState = Literal["live", "running", "ended"]  # simulator run, carried on I13


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VitalsReading(Model):  # I1
    wearable_id: int | None = None
    ts: Ts = None
    hr: float | None = None
    rr_intervals_ms: list[int] | None = None
    contact: bool | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None


class Triage(Model):
    sbp: float | None = None
    dbp: float | None = None
    alertness: Alertness | None = None
    pain: int | None = None
    on_oxygen: bool | None = None
    level: int | None = None  # ESI 1-5


class IntakeRecord(Model):  # I2
    patient_id: str | None = None
    name: str | None = None  # the person's name, shown on the board
    wearable_id: int | None = None
    arrival_ts: Ts = None
    age: float | None = None
    sex: Sex | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    pregnant: bool | None = None
    conditions: list[Condition] | None = None
    custom_conditions: list[str] | None = None  # typed by the nurse beside the checklist
    medications: list[str] | None = None
    chief_complaint: str | None = None
    triage: Triage | None = None


class WearableAssignment(Model):  # I3
    wearable_id: int | None = None
    patient_id: str | None = None
    assigned_ts: Ts = None


class PatientContext(IntakeRecord):  # I4
    bmi: float | None = None
    drug_classes: list[str] | None = None
    unmatched_medications: list[str] | None = None


class Adjustment(Model):
    rule_id: str | None = None
    vital: Vital | None = None
    bound: Bound | None = None
    value: float | None = None
    tier: Literal["danger", "warning"] | None = None  # null means danger; drafted rules use warning


class ContextAdjustments(Model):  # I5
    patient_id: str | None = None
    adjustments: list[Adjustment] | None = None


class PeriodSummary(Model):  # I6
    patient_id: str | None = None
    period_ts: Ts = None
    hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None
    clean_seconds: int | None = None


class VitalValues(Model):
    hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None


class LiveWindow(Model):  # I13
    patient_id: str | None = None
    window_end_ts: Ts = None
    hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None
    clean_seconds: int | None = None
    latest: VitalValues | None = None  # newest clean second, for the dashboard's live numbers
    run_state: RunState | None = None


class VitalRange(Model):
    safe_low: float | None = None
    safe_high: float | None = None
    danger_low: float | None = None
    danger_high: float | None = None
    source: RangeSource | None = None
    reasons: list[str] | None = None


class PatientRanges(Model):  # I8
    patient_id: str | None = None
    hr: VitalRange | None = None
    resp_rate: VitalRange | None = None
    spo2: VitalRange | None = None
    temp_c: VitalRange | None = None
    sbp: VitalRange | None = None


class News2Points(Model):
    resp_rate: int | None = None
    spo2: int | None = None
    on_oxygen: int | None = None  # 0 or 2
    sbp: int | None = None
    hr: int | None = None
    alertness: int | None = None
    temp_c: int | None = None


class VitalLevels(Model):
    hr: Level | None = None
    resp_rate: Level | None = None
    spo2: Level | None = None
    temp_c: Level | None = None


class RiskResult(Model):  # I9
    patient_id: str | None = None
    ts: Ts = None
    level: Level | None = None
    vital: Vital | None = None
    reason: str | None = None
    vital_levels: VitalLevels | None = None
    vital_values: VitalValues | None = None
    news2: int | None = None  # null when the latest I14 is over 60 s older than the period
    news2_points: News2Points | None = None
    trend_prob_fast: float | None = None
    trend_tier: TrendTier | None = None
    trend_reason_fast: str | None = None


class Alert(Model):  # I10
    alert_id: str | None = None
    patient_id: str | None = None
    ts: Ts = None
    severity: Severity | None = None
    trigger: Trigger | None = None
    vital: Vital | None = None
    supersedes: list[str] | None = None  # alert_ids this alert replaces
    resolved: bool | None = None  # true on a re-sent update once the problem has cleared
    message: str | None = None


class Acknowledgment(Model):  # I11
    alert_id: str | None = None
    ts: Ts = None


class ScenarioTrigger(Model):  # I12
    scenario_id: str | None = None
    patient_id: str | None = None
    start_ts: Ts = None


class LiveNews2(Model):  # I14
    patient_id: str | None = None
    ts: Ts = None
    news2: int | None = None
    news2_points: News2Points | None = None


SourceKind = Literal["pmid", "pmc", "doi", "guideline_url"]
ConditionStatus = Literal["found", "ambiguous", "not_found", "checklist", "unavailable"]  # unavailable: the vocabulary service failed


class Source(Model):
    kind: SourceKind | None = None
    id: str | None = None
    title: str | None = None
    year: int | None = None
    passage: str | None = None


class EvidenceItem(Model):
    rule_id: str | None = None
    fact: str | None = None
    quote: str | None = None
    sources: list[Source] | None = None  # drafted items only
    unreviewed: bool | None = None  # true for drafted items


class AdjustmentEvidence(Model):  # I15
    patient_id: str | None = None
    ts: Ts = None
    items: list[EvidenceItem] | None = None
    quote_found: bool | None = None
    model: str | None = None


class Candidate(Model):
    canonical: str | None = None
    code: str | None = None


class ResolvedCondition(Model):
    typed: str | None = None
    canonical: str | None = None
    vocabulary: str | None = None
    code: str | None = None
    status: ConditionStatus | None = None
    candidates: list[Candidate] | None = None  # for ambiguous: shown as not applied
    checklist: Condition | None = None  # for checklist: the flag the typed term maps to


class ConditionResolution(Model):  # I16
    patient_id: str | None = None
    ts: Ts = None
    items: list[ResolvedCondition] | None = None


class DraftPick(Model):
    """What the model may choose. There is no value field: the number comes from the limit menu."""
    vital: Vital | None = None
    bound: Bound | None = None
    menu_id: str | None = None


class DraftedRule(Model):  # I17
    vocabulary: str | None = None
    code: str | None = None
    canonical: str | None = None
    picks: list[DraftPick] | None = None
    sources: list[Source] | None = None
    evidence_label: Literal["strong", "medium", "weak"] | None = None
    retrieved_ts: Ts = None
    evidence_hash: str | None = None
    gates: dict[str, bool] | None = None


class MenuEntry(Model):
    """One allowed warning step (I7 limit_menu.json). relative: tighten the safe edge by amount;
    absolute: amount is the new safe edge."""
    id: str | None = None
    vital: Vital | None = None
    bound: Bound | None = None
    kind: Literal["relative", "absolute"] | None = None
    amount: float | None = None
    label: str | None = None
    source: str | None = None


class LimitMenu(Model):  # I7 limit_menu.json
    version: int | None = None
    entries: list[MenuEntry] | None = None


class BaselineConfig(Model):
    """Personal baseline settings (T3). Times are minutes of wall-clock, not row counts.
    Unlike other models these have real defaults (the shipped config.json values) so a missing
    field can never crash the engine."""
    min_minutes: float = 10
    arrival_check_minutes: float = 3
    learn_minutes: float = 30
    min_clean_seconds: int = 20
    n0_min: float = 0.5
    n0_max: float = 5
    k: float = 2.5
    spread_floor: dict[str, float] = {"hr": 5, "resp_rate": 1}  # per vital, vital units
    min_width: dict[str, float] = {"hr": 16, "resp_rate": 6}


class AlertConfig(Model):
    """Alert logic settings (T4), minutes. Real defaults like BaselineConfig; T4 tunes the windows."""
    warning_persisted_minutes: float = 5
    vital_danger_minutes: float = 2
    news2_total_minutes: float = 2
    trend_minutes: float = 5
    max_gap_minutes: float = 10
    clear_minutes: float = 5
    ack_cooldown_minutes: float = 15


class TrendConfig(Model):
    """Fast trend settings (T6). The cutoff is set from MIMIC at training time."""
    fast_min_clean_minutes: float = 15
    fast_warning_cutoff: float = 0.5


class ModelConfig(Model):  # I7 config.json
    baseline: BaselineConfig | None = None
    alerts: AlertConfig | None = None
    trend: TrendConfig | None = None


class RuleAdjustment(Model):
    vital: Vital | None = None
    bound: Bound | None = None
    value: float | None = None


class RuleSpec(Model):
    """One allowed context-adjustment rule (I7 rules.json). Values are proposals; labels name rules, not numbers."""
    id: str | None = None
    adjustments: list[RuleAdjustment] | None = None
    status: Literal["proposed", "confirmed"] | None = None
    trigger_source: Literal["structured", "text", "both"] | None = None
    fires_when: str | None = None
    does_not_fire: str | None = None
    sources: list[str] | None = None
    evidence: Literal["strong", "medium", "weak"] | None = None
    flag: str | None = None  # why a value is unconfirmed


class RulesFile(Model):  # I7 rules.json
    rules: list[RuleSpec] | None = None


class QuantileFit(Model):
    intercept: float | None = None
    coef: dict[str, float] | None = None


class TargetFit(Model):
    q025: QuantileFit | None = None
    q50: QuantileFit | None = None
    q975: QuantileFit | None = None


class ReferenceBand(Model):
    safe_low: float | None = None
    safe_high: float | None = None


class TempReference(Model):
    safe_low: float | None = None
    safe_high: float | None = None
    ref_age: float | None = None
    shift_per_decade: float | None = None


class RangesMeta(Model):
    cycle: str | None = None
    n_train: int | None = None
    n_holdout: int | None = None
    fit_date: str | None = None
    coverage: dict[str, float] | None = None
    notes: str | None = None


class RangesFile(Model):  # I7 ranges.json
    meta: RangesMeta | None = None
    features: list[str] | None = None
    feature_clamp: dict[str, list[float]] | None = None  # feature -> [low, high] applied before predicting
    cohort_means: dict[str, float] | None = None  # fallback for a missing continuous feature
    targets: dict[str, TargetFit] | None = None  # "hr", "sbp"
    reference: dict[str, ReferenceBand | TempReference] | None = None  # "resp_rate", "spo2", "temp_c"


# WebSocket envelope: {"type": "<interface ID>", "data": {...}}
Envelope = Literal["I1", "I8", "I9", "I10", "I11", "I12", "I13", "I14"]


class WsMessage(Model):
    type: Envelope | None = None
    data: dict | None = None
    sentry_trace: str | None = None  # trace headers from the sender, so a Sentry trace spans processes
    baggage: str | None = None


INTERFACES: dict[str, type[Model]] = {
    "I1": VitalsReading, "I2": IntakeRecord, "I3": WearableAssignment,
    "I4": PatientContext, "I5": ContextAdjustments, "I6": PeriodSummary,
    "I7": ModelConfig, "I8": PatientRanges, "I9": RiskResult, "I10": Alert,
    "I11": Acknowledgment, "I12": ScenarioTrigger, "I13": LiveWindow,
    "I14": LiveNews2, "I15": AdjustmentEvidence, "I16": ConditionResolution, "I17": DraftedRule,
}
