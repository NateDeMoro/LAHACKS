"""Shared models for interfaces I1-I15. Source of truth: notes/component-map.md.

Every field is nullable with default None, unknown fields are rejected, and
timestamps must be timezone-aware.
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


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    wearable_id: int | None = None
    arrival_ts: Ts = None
    age: float | None = None
    sex: Sex | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    pregnant: bool | None = None
    conditions: list[Condition] | None = None
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


class ContextAdjustments(Model):  # I5
    patient_id: str | None = None
    adjustments: list[Adjustment] | None = None


class MinuteSummary(Model):  # I6
    patient_id: str | None = None
    minute_ts: Ts = None
    hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None
    clean_seconds: int | None = None


class LiveWindow(Model):  # I13
    patient_id: str | None = None
    window_end_ts: Ts = None
    hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None
    temp_c: float | None = None
    clean_seconds: int | None = None


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


class RiskResult(Model):  # I9
    patient_id: str | None = None
    ts: Ts = None
    level: Level | None = None
    vital: Vital | None = None
    reason: str | None = None
    news2: int | None = None
    news2_points: News2Points | None = None
    trend_prob_fast: float | None = None
    trend_prob_slow: float | None = None


class Alert(Model):  # I10
    alert_id: str | None = None
    patient_id: str | None = None
    ts: Ts = None
    severity: Severity | None = None
    trigger: Trigger | None = None
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


class EvidenceItem(Model):
    rule_id: str | None = None
    fact: str | None = None
    quote: str | None = None


class AdjustmentEvidence(Model):  # I15
    patient_id: str | None = None
    ts: Ts = None
    items: list[EvidenceItem] | None = None
    quote_found: bool | None = None
    model: str | None = None


class ModelConfig(Model):  # I7 config.json
    n0: int | None = None
    persistence_windows: dict[str, int] | None = None
    probability_cutoffs: dict[str, float] | None = None


# WebSocket envelope: {"type": "<interface ID>", "data": {...}}
Envelope = Literal["I1", "I8", "I9", "I10", "I11", "I12", "I13", "I14"]


class WsMessage(Model):
    type: Envelope | None = None
    data: dict | None = None


INTERFACES: dict[str, type[Model]] = {
    "I1": VitalsReading, "I2": IntakeRecord, "I3": WearableAssignment,
    "I4": PatientContext, "I5": ContextAdjustments, "I6": MinuteSummary,
    "I7": ModelConfig, "I8": PatientRanges, "I9": RiskResult, "I10": Alert,
    "I11": Acknowledgment, "I12": ScenarioTrigger, "I13": LiveWindow,
    "I14": LiveNews2, "I15": AdjustmentEvidence,
}
