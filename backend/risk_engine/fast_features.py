"""Feature function for the T6 fast trend model, shared by training (training/train_fast.py) and live
(backend/risk_engine/fast_model.py). Use when you need the model inputs for one minute from the recent minute values.

Input is timestamp based: for each vital, parallel sequences of minute timestamps (minutes, any origin) and
values (None or NaN = not observed). Windows are (now - W, now]. A window with fewer than FILL_FRACTION of its
W minutes observed is "unfilled" and all its features are NaN (so the 30-minute window is NaN until ~18 minutes
of data exist). Must not import training code.
"""
import math

import numpy as np

VITALS = ("hr", "resp_rate", "spo2")
WINDOWS = (5, 15, 30)
FILL_FRACTION = 0.6
# NEWS2 score-3 range edges, inclusive: low edge means value <= edge is danger, high edge means value >= edge.
LOW_EDGE = {"hr": 40.0, "resp_rate": 8.0, "spo2": 91.0}
HIGH_EDGE = {"hr": 131.0, "resp_rate": 25.0}
STATS = ("med", "slope", "spread", "min", "max")
SPREAD_FLOOR = {"hr": 5.0, "resp_rate": 1.0, "spo2": 1.0}  # for the distance baseline (config spread_floor for hr/rr)


def _names():
    out = []
    for v in VITALS:
        for w in WINDOWS:
            out += [f"{v}_{w}_{s}" for s in STATS]
            if v in LOW_EDGE:
                out.append(f"{v}_{w}_dlow")
            if v in HIGH_EDGE:
                out.append(f"{v}_{w}_dhigh")
    return out


FEATURE_NAMES = _names()


def compute_features(series: dict, now: float) -> dict:
    """series: {vital: (times, values)}; now: the current minute timestamp. Returns {feature name: float}.
    Use when scoring a minute, in training or live; missing vitals or unfilled windows give NaN."""
    out = {}
    for v in VITALS:
        times, vals = series.get(v, ((), ()))
        t = np.asarray(times, dtype=float)
        x = np.asarray([math.nan if y is None else y for y in vals], dtype=float)
        ok = np.isfinite(x) & (t <= now)
        t, x = t[ok], x[ok]
        for w in WINDOWS:
            sel = t > now - w
            tw, xw = t[sel], x[sel]
            filled = len(xw) >= max(3, math.ceil(FILL_FRACTION * w))
            if filled:
                med = float(np.median(xw))
                tc = tw - tw.mean()
                denom = float((tc * tc).sum())
                slope = float((tc * (xw - xw.mean())).sum() / denom) if denom > 0 else 0.0
                vals_w = {"med": med, "slope": slope, "spread": float(xw.std()),
                          "min": float(xw.min()), "max": float(xw.max())}
            else:
                med = math.nan
                vals_w = {s: math.nan for s in STATS}
            for s in STATS:
                out[f"{v}_{w}_{s}"] = vals_w[s]
            if v in LOW_EDGE:
                out[f"{v}_{w}_dlow"] = med - LOW_EDGE[v]
            if v in HIGH_EDGE:
                out[f"{v}_{w}_dhigh"] = HIGH_EDGE[v] - med
    return out


def distance_score(f: dict) -> float:
    """Baseline 1. Use when scoring by closeness to danger: the closest any vital's 5-minute median sits to a
    danger edge, in units of that vital's 15-minute spread (floored); higher means closer. Max over vitals and edges."""
    best = -math.inf
    for v in VITALS:
        spread = f.get(f"{v}_15_spread", math.nan)
        scale = max(SPREAD_FLOOR[v], spread) if math.isfinite(spread) else SPREAD_FLOOR[v]
        for suffix in ("dlow", "dhigh"):
            d = f.get(f"{v}_5_{suffix}", math.nan)
            if math.isfinite(d):
                best = max(best, -d / scale)
    return best if math.isfinite(best) else -1e9


def extrapolation_score(f: dict, horizon: float = 15.0) -> float:
    """Baseline 2. Use when scoring by straight-line extrapolation: how far (raw units) the 15-minute slope would
    carry a vital past a danger edge `horizon` minutes after its 5-minute median; max over vitals and edges."""
    best = -math.inf
    for v in VITALS:
        slope = f.get(f"{v}_15_slope", math.nan)
        if not math.isfinite(slope):
            continue
        d = f.get(f"{v}_5_dlow", math.nan)
        if math.isfinite(d):
            best = max(best, -(d + slope * horizon))
        d = f.get(f"{v}_5_dhigh", math.nan)
        if math.isfinite(d):
            best = max(best, -(d - slope * horizon))
    return best if math.isfinite(best) else -1e9
