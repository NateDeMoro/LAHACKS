"""Fast trend model (T6). Use when trend.py asks whether HR, breathing or SpO2 is heading for the danger range
within about 15 minutes.

Shipped model: the distance-to-threshold baseline (LightGBM did not beat it on held-out MIMIC patients, see
notes/decisions.md), so no model file and no LightGBM import is needed. The score is how close the closest vital's
5-minute median is to a NEWS2 score-3 edge, in units of that vital's 15-minute spread (higher = closer); I9's
trend_prob_fast carries this score, not a probability. The warning cutoff is trend.fast_warning_cutoff in
models/config.json. Features come from fast_features.py, the same code training used."""
from backend.risk_engine import fast_features as ff

_PHRASES = {
    ("spo2", "low"): ("SpO2 falling", "SpO2 near danger"),
    ("resp_rate", "high"): ("breathing speeding up", "breathing near danger"),
    ("resp_rate", "low"): ("breathing slowing down", "breathing near danger"),
    ("hr", "high"): ("heart rate rising", "heart rate near danger"),
    ("hr", "low"): ("heart rate falling", "heart rate near danger"),
}


def load() -> bool:
    """The baseline needs no files; always available."""
    return True


def predict(history) -> tuple[float, str] | None:
    """history: a trend.TrendHistory. Returns (closeness score, one-line reason), or None with no usable vitals."""
    rows = list(history.rows)
    if not rows:
        return None
    t0 = rows[0].ts
    t = [(r.ts - t0).total_seconds() / 60 for r in rows]
    series = {v: (t, [getattr(r, v) for r in rows]) for v in ff.VITALS}
    f = ff.compute_features(series, t[-1])
    score, vital, edge = ff.distance_detail(f)
    if vital is None:
        return None
    falling_toward = f.get(f"{vital}_15_slope", 0.0) * (-1 if edge == "low" else 1) > 0
    return score, _PHRASES[(vital, edge)][0 if falling_toward else 1]
