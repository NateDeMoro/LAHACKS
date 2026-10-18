"""Fast trend model (T6). Use when trend.py asks whether HR, breathing or SpO2 is heading for the danger range
within about 15 minutes.

Four interchangeable scorers share fast_features.py with training; METHOD picks the shipped one:
  "distance"      Rule 1, closeness of the 5-minute median to a NEWS2 score-3 edge in spreads (shipped).
  "extrapolation" Rule 2, how far the 15-minute slope carries a vital past an edge in 15 minutes.
  "logreg"        small logistic regression over the six per-vital rule scores (models/fast_15_logreg.json).
  "forecast"      LightGBM forecasts of each vital's lowest/highest value in the next 15 minutes
                  (models/fast_15_forecast.json + fast_15_forecast_*.txt, loaded lazily); score = how far the
                  cautious (10%/90%) forecast lands past the danger edge, same units as Rule 2.
To switch: change METHOD here and set trend.fast_warning_cutoff in models/config.json to CUTOFFS[METHOD]
(for "logreg" and "forecast" the cutoff is in their JSON). No model file or LightGBM import is needed for the rules.
I9 trend_prob_fast carries the score, not a probability. Held-out MIMIC numbers: notes/decisions.md."""
import json
import math
from pathlib import Path

import numpy as np

from backend.risk_engine import fast_features as ff

METHOD = "distance"
CUTOFFS = {"distance": -0.47, "extrapolation": 3.26}
MODELS = Path(__file__).resolve().parents[2] / "models"
LOGREG_PATH = MODELS / "fast_15_logreg.json"
FORECAST_PATH = MODELS / "fast_15_forecast.json"

_PHRASES = {
    ("spo2", "low"): ("SpO2 falling", "SpO2 near danger"),
    ("resp_rate", "high"): ("breathing speeding up", "breathing near danger"),
    ("resp_rate", "low"): ("breathing slowing down", "breathing near danger"),
    ("hr", "high"): ("heart rate rising", "heart rate near danger"),
    ("hr", "low"): ("heart rate falling", "heart rate near danger"),
}
_logreg = None
_forecast = None  # {"meta": json, "models": [(target dict, Booster)]}


def load() -> bool:
    """Rules need no files. The logistic model needs its JSON; False means no model."""
    global _logreg, _forecast
    if METHOD == "forecast":
        return _load_forecast()
    if METHOD != "logreg":
        return True
    if not LOGREG_PATH.exists():
        return False
    _logreg = json.loads(LOGREG_PATH.read_text())
    return True


def _load_forecast() -> bool:
    """Use when METHOD is "forecast": reads the bundle JSON and the cautious-quantile models (LightGBM imported here)."""
    global _forecast
    if not FORECAST_PATH.exists():
        return False
    import lightgbm as lgb
    meta = json.loads(FORECAST_PATH.read_text())
    _forecast = {"meta": meta, "models": [(t, lgb.Booster(model_file=str(MODELS / t["cautious_file"])))
                                          for t in meta["targets"]]}
    return True


def forecast_values(f: dict) -> list[tuple[str, str, float, float]]:
    """Use when you need the cautious forecasts for one minute's features f. Returns
    (vital, kind, cautious forecast, score) per target whose vital has a filled 5-minute window; score is the
    forecast's distance past the danger edge (positive = past it), the same convention as Rule 2."""
    x = np.array([[f.get(n, math.nan) for n in _forecast["meta"]["features"]]], float)
    out = []
    for t, booster in _forecast["models"]:
        med = f.get(f"{t['vital']}_5_med", math.nan)
        if not math.isfinite(med):
            continue
        fc = med + float(booster.predict(x, num_threads=1)[0])
        edge = ff.LOW_EDGE[t["vital"]] if t["kind"] == "low" else ff.HIGH_EDGE[t["vital"]]
        out.append((t["vital"], t["kind"], fc, edge - fc if t["kind"] == "low" else fc - edge))
    return out


_FORECAST_WORDS = {"spo2": "SpO2 may reach {:.0f}%", "resp_rate": "breathing may reach {:.0f}/min",
                   "hr": "heart rate may reach {:.0f} bpm"}


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
    if METHOD == "forecast":
        vals = forecast_values(f)
        if not vals:
            return None
        vital, _, fc, score = max(vals, key=lambda v: v[3])
        return score, _FORECAST_WORDS[vital].format(fc) + " within 15 min"
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
