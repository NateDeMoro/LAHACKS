"""Fast trend model (T6). Use when trend.py asks whether HR, breathing or SpO2 is heading for the danger range
within about 15 minutes.

Three interchangeable scorers share fast_features.py with training; METHOD picks the shipped one:
  "distance"      Rule 1, closeness of the 5-minute median to a NEWS2 score-3 edge in spreads (shipped).
  "extrapolation" Rule 2, how far the 15-minute slope carries a vital past an edge in 15 minutes.
  "logreg"        small logistic regression over the six per-vital rule scores (models/fast_15_logreg.json).
To switch: change METHOD here and set trend.fast_warning_cutoff in models/config.json to CUTOFFS[METHOD]
(for "logreg" the cutoff is in the JSON). No model file or LightGBM import is needed for the rules.
I9 trend_prob_fast carries the score, not a probability. Held-out MIMIC numbers: notes/decisions.md."""
import json
import math
from pathlib import Path

import numpy as np

from backend.risk_engine import fast_features as ff

METHOD = "distance"
CUTOFFS = {"distance": -0.47, "extrapolation": 3.26}
LOGREG_PATH = Path(__file__).resolve().parents[2] / "models" / "fast_15_logreg.json"

_PHRASES = {
    ("spo2", "low"): ("SpO2 falling", "SpO2 near danger"),
    ("resp_rate", "high"): ("breathing speeding up", "breathing near danger"),
    ("resp_rate", "low"): ("breathing slowing down", "breathing near danger"),
    ("hr", "high"): ("heart rate rising", "heart rate near danger"),
    ("hr", "low"): ("heart rate falling", "heart rate near danger"),
}
_logreg = None


def load() -> bool:
    """Rules need no files. The logistic model needs its JSON; False means no model."""
    global _logreg
    if METHOD != "logreg":
        return True
    if not LOGREG_PATH.exists():
        return False
    _logreg = json.loads(LOGREG_PATH.read_text())
    return True


def _reason(f: dict, vital: str) -> str:
    dlow = f.get(f"{vital}_5_dlow", math.inf)
    dhigh = f.get(f"{vital}_5_dhigh", math.inf)
    edge = "low" if (math.isfinite(dlow) and dlow <= dhigh) or not math.isfinite(dhigh) else "high"
    toward = f.get(f"{vital}_15_slope", 0.0) * (-1 if edge == "low" else 1) > 0
    return _PHRASES[(vital, edge)][0 if toward else 1]


def predict(history) -> tuple[float, str] | None:
    """history: a trend.TrendHistory. Returns (score, one-line reason), or None with no usable vitals."""
    rows = list(history.rows)
    if not rows:
        return None
    t0 = rows[0].ts
    t = [(r.ts - t0).total_seconds() / 60 for r in rows]
    f = ff.compute_features({v: (t, [getattr(r, v) for r in rows]) for v in ff.VITALS}, t[-1])
    per = ff.vital_rule_scores(f)
    if METHOD == "distance":
        score = ff.distance_score(f)
        vals = per[:3]
    elif METHOD == "extrapolation":
        score = ff.extrapolation_score(f)
        vals = per[3:]
    else:
        m = _logreg
        x = np.array(per, float)
        z = (np.where(np.isfinite(x), x, np.array(m["fill"])) - np.array(m["mean"])) / np.array(m["scale"])
        contrib = z * np.array(m["coef_standardized"])
        score = float(contrib.sum() + m["intercept"])
        vals = [contrib[i] + contrib[i + 3] for i in range(3)]
    if score <= -1e9 or not any(math.isfinite(v) for v in vals):
        return None
    vital = ff.VITALS[int(np.nanargmax(vals))]
    return score, _reason(f, vital)
