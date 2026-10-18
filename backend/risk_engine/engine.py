"""Risk engine: NEWS2 every second; population ranges at intake; personal baseline and I9 every minute."""
import json
from pathlib import Path
from datetime import timedelta
from typing import Callable

from backend.config import CONFIG
from backend.contracts import (BaselineConfig, ContextAdjustments, LiveNews2, LiveWindow,
                               MinuteSummary, ModelConfig, PatientContext, PatientRanges,
                               RiskResult, TrendConfig, VitalLevels, VitalRange, VitalValues)
from backend.risk_engine import news2, ranges
from backend.risk_engine.baseline import PersonalBaseline
from backend.risk_engine.trend import Trend

CONFIG_PATH = Path(__file__).resolve().parents[2] / "models" / "config.json"

_LABEL = {"hr": "heart rate", "resp_rate": "breathing", "spo2": "SpO2", "temp_c": "temperature"}
_UNIT = {"hr": "/min", "resp_rate": "/min", "spo2": "%", "temp_c": "C"}
_RANK = {"safe": 0, "warning": 1, "danger": 2}
NEWS2_MAX_AGE = timedelta(seconds=60)  # a live NEWS2 older than this is not shown beside the minute


def default_ranges(patient_id: str | None) -> PatientRanges:
    """NEWS2 score-0 range as safe, score-3 values as danger (edges inclusive)."""
    return ranges.score0_ranges(patient_id)


def load_config(path: Path = CONFIG_PATH) -> ModelConfig:
    return ModelConfig(**json.loads(path.read_text()))


def classify(v: float, rng: VitalRange, vital: str | None = None) -> str:
    """Band a reading against a range. With the vital named, the reading is rounded as NEWS2 does."""
    if vital:
        v = news2.rounded(vital, v)
    if (rng.danger_low is not None and v <= rng.danger_low) or \
       (rng.danger_high is not None and v >= rng.danger_high):
        return "danger"
    if (rng.safe_low is not None and v < rng.safe_low) or \
       (rng.safe_high is not None and v > rng.safe_high):
        return "warning"
    return "safe"


class RiskEngine:
    def __init__(self, config: ModelConfig | None = None):
        self.config = config or load_config()
        self.context: dict[str, PatientContext] = {}
        self.intake_ranges: dict[str, PatientRanges] = {}  # population I8 at intake; the simulator reads this one
        self.baselines: dict[str, PersonalBaseline] = {}
        self.latest: dict[str, LiveNews2] = {}
        self.trend = Trend(self.config.trend or TrendConfig(),
                           (self.config.baseline or BaselineConfig()).min_clean_seconds)
        self.ranges_listener: Callable[[PatientRanges], None] | None = None  # called when a patient's I8 changes

    @property
    def ranges(self) -> dict[str, PatientRanges]:
        """Current I8 per patient (population, narrowed once the personal baseline kicks in)."""
        return {pid: b.ranges for pid, b in self.baselines.items()}

    def bed_label(self, patient_id: str) -> str:
        """Bed name for alert messages: wearable from the stored I4, else the patient_id."""
        ctx = self.context.get(patient_id)
        wearable = ctx.wearable_id if ctx else None
        return CONFIG.beds.labels.get(wearable, patient_id)

    def _start(self, patient_id: str, population: PatientRanges, centres: dict[str, float]):
        self.intake_ranges[patient_id] = population
        if patient_id in self.baselines:  # intake after readings started (or repeated): keep what was learned
            self.baselines[patient_id].rebase(population, centres)
        else:
            self.baselines[patient_id] = PersonalBaseline(
                self.config.baseline or BaselineConfig(), population, centres)

    def seed_trend_history(self, patient_id: str, rows: list[MinuteSummary]):
        """Pre-roll for simulated runs: feeds the trend layer only, never the baseline, alerts or store."""
        self.trend.seed(patient_id, rows)

    def on_intake(self, ctx: PatientContext, adjustments: ContextAdjustments | None = None
                  ) -> PatientRanges:
        self.context[ctx.patient_id] = ctx
        population = ranges.apply_i5(ranges.build_population_ranges(ctx), adjustments)
        self._start(ctx.patient_id, population, ranges.population_centres(ctx))
        return self.baselines[ctx.patient_id].ranges

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
        if m.patient_id not in self.baselines:  # seen without an intake: plain NEWS2 bands
            self._start(m.patient_id, default_ranges(m.patient_id), ranges.population_centres(None))
        base = self.baselines[m.patient_id]
        if base.update(m) and self.ranges_listener:
            self.ranges_listener(base.ranges)
        current = base.ranges
        level, vital, reason = "safe", None, None
        levels: dict[str, str | None] = {}
        for name in ("hr", "resp_rate", "spo2", "temp_c"):
            v = getattr(m, name)
            levels[name] = None if v is None else classify(v, getattr(current, name), name)
            if levels[name] and _RANK[levels[name]] > _RANK[level]:
                level, vital = levels[name], name
                reason = f"{_LABEL[name]} {v:g}{_UNIT[name]}, {level}"
        tr = self.trend.update(m, levels, level, reason)
        live = self.latest.get(m.patient_id)
        if live and m.minute_ts and live.ts and m.minute_ts - live.ts > NEWS2_MAX_AGE:
            live = None
        return RiskResult(
            patient_id=m.patient_id, ts=m.minute_ts, level=tr.level, vital=vital, reason=tr.reason,
            vital_levels=VitalLevels(**levels),
            vital_values=VitalValues(hr=m.hr, resp_rate=m.resp_rate, spo2=m.spo2, temp_c=m.temp_c),
            news2=live.news2 if live else None,
            news2_points=live.news2_points if live else None,
            trend_prob_fast=tr.prob, trend_tier=tr.tier, trend_reason_fast=tr.trend_reason,
        )
