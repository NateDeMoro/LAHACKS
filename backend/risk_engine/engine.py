"""Stub risk engine: plain NEWS2 as I9/I14 with fixed population ranges."""
from datetime import timedelta

from backend.contracts import (ContextAdjustments, LiveNews2, LiveWindow, MinuteSummary,
                               PatientContext, PatientRanges, RiskResult, VitalRange)
from backend.risk_engine import news2

_LABEL = {"hr": "heart rate", "resp_rate": "breathing", "spo2": "SpO2", "temp_c": "temperature"}
_UNIT = {"hr": "/min", "resp_rate": "/min", "spo2": "%", "temp_c": "C"}
_RANK = {"safe": 0, "warning": 1, "danger": 2}


def default_ranges(patient_id: str | None) -> PatientRanges:
    """NEWS2 score-0 range as safe, score-3 values as danger (edges inclusive)."""
    def r(sl, sh, dl, dh):
        return VitalRange(safe_low=sl, safe_high=sh, danger_low=dl, danger_high=dh,
                          source="population", reasons=[])
    return PatientRanges(
        patient_id=patient_id,
        hr=r(51, 90, 40, 131), resp_rate=r(12, 20, 8, 25),
        spo2=r(96, 100, 91, None), temp_c=r(36.1, 38.0, 35.0, None),
        sbp=r(111, 219, 90, 220),
    )


def classify(v: float, rng: VitalRange) -> str:
    if (rng.danger_low is not None and v <= rng.danger_low) or \
       (rng.danger_high is not None and v >= rng.danger_high):
        return "danger"
    if (rng.safe_low is not None and v < rng.safe_low) or \
       (rng.safe_high is not None and v > rng.safe_high):
        return "warning"
    return "safe"


class RiskEngine:
    def __init__(self):
        self.context: dict[str, PatientContext] = {}
        self.ranges: dict[str, PatientRanges] = {}
        self.latest: dict[str, LiveNews2] = {}

    def on_intake(self, ctx: PatientContext, adjustments: ContextAdjustments | None = None
                  ) -> PatientRanges:
        # I5 is accepted and ignored in the stub (applied by T2/B3 later)
        self.context[ctx.patient_id] = ctx
        self.ranges[ctx.patient_id] = default_ranges(ctx.patient_id)
        return self.ranges[ctx.patient_id]

    def on_second(self, w: LiveWindow) -> LiveNews2:
        tri = self.context[w.patient_id].triage if w.patient_id in self.context else None
        total, pts = news2.score(
            resp_rate=w.resp_rate, spo2=w.spo2, hr=w.hr, temp_c=w.temp_c,
            sbp=tri.sbp if tri else None, alertness=tri.alertness if tri else None,
            on_oxygen=tri.on_oxygen if tri else None)
        out = LiveNews2(patient_id=w.patient_id, ts=w.window_end_ts, news2=total, news2_points=pts)
        self.latest[w.patient_id] = out
        return out

    def on_minute(self, m: MinuteSummary) -> RiskResult:
        ranges = self.ranges.get(m.patient_id) or default_ranges(m.patient_id)
        level, vital, reason = "safe", None, None
        for name in ("hr", "resp_rate", "spo2", "temp_c"):
            v = getattr(m, name)
            if v is None:
                continue
            lv = classify(v, getattr(ranges, name))
            if _RANK[lv] > _RANK[level]:
                level, vital = lv, name
                reason = f"{_LABEL[name]} {v:g}{_UNIT[name]}, {lv}"
        live = self.latest.get(m.patient_id)
        return RiskResult(
            patient_id=m.patient_id, ts=m.minute_ts, level=level, vital=vital, reason=reason,
            news2=live.news2 if live else None,
            news2_points=live.news2_points if live else None,
        )
