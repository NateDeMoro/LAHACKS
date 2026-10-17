"""Pure NEWS2 scoring (SpO2 scale 1). Use when scoring any vital set."""
import math
from decimal import ROUND_HALF_UP, Decimal

from backend.contracts import News2Points


def _round(v, places=0):
    """Round half up (20.5 -> 21, 35.05 -> 35.1); avoids half-to-even surprises like 24.5 -> 24."""
    return float(Decimal(str(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def rounded(vital: str, v: float) -> float:
    """A reading rounded as NEWS2 does before banding (temperature to 0.1, the rest to whole numbers)."""
    return _round(v, 1 if vital == "temp_c" else 0)


def _band(v, bands):
    """bands: list of (upper_inclusive, points); last entry catches the rest."""
    for upper, pts in bands:
        if v <= upper:
            return pts
    return bands[-1][1]


def score_rr(v):
    return _band(_round(v), [(8, 3), (11, 1), (20, 0), (24, 2), (float("inf"), 3)])


def score_spo2(v):
    return _band(_round(v), [(91, 3), (93, 2), (95, 1), (float("inf"), 0)])


def score_sbp(v):
    return _band(_round(v), [(90, 3), (100, 2), (110, 1), (219, 0), (float("inf"), 3)])


def score_hr(v):
    return _band(_round(v), [(40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (float("inf"), 3)])


def score_temp(v):
    return _band(_round(v, 1), [(35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (float("inf"), 2)])


def score_alertness(v):
    return 0 if v == "alert" else 3


def score_oxygen(v):
    return 2 if v else 0


def _opt(fn, v):
    # NaN and infinity count as missing (the contract models reject them, but direct callers can pass them)
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return fn(v)


def score(resp_rate=None, spo2=None, on_oxygen=None, sbp=None, hr=None,
          alertness=None, temp_c=None) -> tuple[int | None, News2Points]:
    """Return (total, points). Null inputs get null points and are left out of the total;
    total is None if every part is null."""
    pts = News2Points(
        resp_rate=_opt(score_rr, resp_rate), spo2=_opt(score_spo2, spo2),
        on_oxygen=_opt(score_oxygen, on_oxygen), sbp=_opt(score_sbp, sbp),
        hr=_opt(score_hr, hr), alertness=_opt(score_alertness, alertness),
        temp_c=_opt(score_temp, temp_c),
    )
    parts = [v for v in pts.model_dump().values() if v is not None]
    return (sum(parts) if parts else None), pts
