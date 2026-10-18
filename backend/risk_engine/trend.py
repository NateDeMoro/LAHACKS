"""Fast trend wiring (Step A). Use when I9 needs trend fields on top of the per-period levels.

Keeps each patient's last 60 minutes of clean minute values, starts after `fast_min_clean_minutes`
of elapsed time, stays null while any vital is in danger (the fast label is not defined there),
and can only raise a safe level to warning. The model itself lives in fast_model.py."""
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.contracts import PeriodSummary, TrendConfig
from backend.risk_engine import fast_model
from backend.risk_engine.baseline import is_clean_period

log = logging.getLogger(__name__)

HISTORY = timedelta(minutes=60)


@dataclass(frozen=True)
class Row:
    ts: datetime
    hr: float | None
    resp_rate: float | None
    spo2: float | None
    merged: bool = False  # two periods already averaged into this row


def _mean(a: float | None, b: float | None) -> float | None:
    return b if a is None else a if b is None else (a + b) / 2


def _merge(first: Row, second: Row) -> Row:
    """Same clock minute: keep the first timestamp, average the vitals."""
    return Row(first.ts, _mean(first.hr, second.hr), _mean(first.resp_rate, second.resp_rate),
               _mean(first.spo2, second.spo2), merged=True)


class TrendHistory:
    """Last 60 minutes of clean one-minute values for one patient."""

    def __init__(self):
        self.rows: deque[Row] = deque()
        self.first_clean: datetime | None = None

    def add(self, m: PeriodSummary):
        if self.first_clean is None:
            self.first_clean = m.period_ts
        row = Row(m.period_ts, m.hr, m.resp_rate, m.spo2)
        last = self.rows[-1] if self.rows else None
        if last and not last.merged and last.ts.replace(second=0, microsecond=0) == m.period_ts.replace(second=0, microsecond=0):
            row = _merge(self.rows.pop(), row)  # the model was trained on one-minute rows; 30 s periods are paired up
        self.rows.append(row)
        while self.rows[0].ts < m.period_ts - HISTORY:
            self.rows.popleft()

    def elapsed_minutes(self, now: datetime) -> float:
        return 0.0 if self.first_clean is None else (now - self.first_clean).total_seconds() / 60


@dataclass(frozen=True)
class TrendOutcome:
    level: str
    reason: str | None
    prob: float | None = None
    tier: str | None = None
    trend_reason: str | None = None


class Trend:
    def __init__(self, cfg: TrendConfig, min_clean_seconds: int | None):
        self.cfg, self.min_clean_seconds = cfg, min_clean_seconds
        self.histories: dict[str, TrendHistory] = {}
        self._failed = False
        try:
            self.model_loaded = fast_model.load()
        except Exception:
            self._log_once("fast trend model failed to load")
            self.model_loaded = False

    def _log_once(self, msg: str):
        if not self._failed:
            self._failed = True
            log.exception(msg)

    def update(self, m: PeriodSummary, levels: dict[str, str | None], level: str,
               reason: str | None) -> TrendOutcome:
        """Feed one period with its classified levels; returns the (possibly raised) level and trend fields."""
        unchanged = TrendOutcome(level, reason)
        if m.period_ts is None or not is_clean_period(m.clean_seconds, self.min_clean_seconds):
            return unchanged
        hist = self.histories.setdefault(m.patient_id, TrendHistory())
        hist.add(m)
        if hist.elapsed_minutes(m.period_ts) < self.cfg.fast_min_clean_minutes or \
           "danger" in levels.values() or not self.model_loaded:
            return unchanged
        try:
            out = fast_model.predict(hist)
        except Exception:
            self._log_once("fast trend model failed")
            return unchanged
        if out is None:
            return unchanged
        prob, trend_reason = out
        if prob < self.cfg.fast_warning_cutoff:
            return TrendOutcome(level, reason, prob)
        if level == "safe":
            level, reason = "warning", trend_reason
        return TrendOutcome(level, reason, prob, "warning", trend_reason)
