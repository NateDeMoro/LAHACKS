"""Population I8: safe bands from the NHANES fit and published references, danger from NEWS2.
Use when building a patient's ranges at intake (T2) or when a component needs the NEWS2 band edges.

Safe is always inside the NEWS2 score-0 range, so a value shown as safe never scores NEWS2 points;
the fit can only tighten it. Danger is the NEWS2 score-3 edge (inclusive) and is not moved here."""
import json
from functools import lru_cache
from pathlib import Path

from backend.contracts import (ContextAdjustments, PatientContext, PatientRanges, RangesFile, TempReference,
                               VitalRange)

RANGES_PATH = Path(__file__).resolve().parents[2] / "models" / "ranges.json"

SCORE0 = {"hr": (51, 90), "resp_rate": (12, 20), "spo2": (96, 100), "temp_c": (36.1, 38.0),
          "sbp": (111, 219)}
DANGER = {"hr": (40, 131), "resp_rate": (8, 25), "spo2": (91, None), "temp_c": (35.0, None),
          "sbp": (90, 220)}
MARGIN = {"hr": 1, "resp_rate": 1, "spo2": 1, "temp_c": 0.1, "sbp": 1}  # safe stays this far inside danger
MIN_WIDTH = {"hr": 20, "sbp": 20, "temp_c": 0.6}  # a fitted band narrower than this is not trusted
MIN_SHIFT = {"hr": 2, "sbp": 2, "temp_c": 0.1}  # smaller shifts are not worth a reason line

_NAME = {"hr": "heart rate", "sbp": "systolic BP", "temp_c": "temperature"}
_ADJ_NAME = {**_NAME, "resp_rate": "breathing rate", "spo2": "SpO2"}
_UNIT = {"hr": "bpm", "sbp": "mmHg", "temp_c": "C"}
_LABEL = {"beta_blocker": "beta-blocker", "ssri": "SSRI", "snri": "SNRI", "copd": "COPD"}
_FLAG_FEATURES_SKIP = {"age", "age_sq", "male", "bmi"}


@lru_cache
def load_ranges(path: Path = RANGES_PATH) -> RangesFile | None:
    """None when no ranges.json exists yet; callers then fall back to the NEWS2 score-0 bands."""
    if not path.exists():
        return None
    return RangesFile(**json.loads(path.read_text()))


def clamp_safe(vital: str, low: float | None, high: float | None) -> tuple[float | None, float | None]:
    """Keep the safe band strictly inside the danger edges (by the vital's margin)."""
    d_low, d_high = DANGER[vital]
    m = MARGIN[vital]
    if low is not None and d_low is not None:
        low = max(low, d_low + m)
    if high is not None and d_high is not None:
        high = min(high, d_high - m)
    return low, high


def apply_i5(pop: PatientRanges, i5: ContextAdjustments | None) -> PatientRanges:
    """Move danger edges inward by the I5 adjustments, then pull the safe band back inside the moved edge.
    Use when a patient's context tightens limits at intake. Loosening, unknown vitals and missing values are
    ignored (I5 says the engine clamps anything else)."""
    out = pop.model_copy(deep=True)
    for a in (i5.adjustments or []) if i5 else []:
        rng = getattr(out, a.vital, None) if a.vital in DANGER else None
        if rng is None or a.bound not in ("low", "high") or a.value is None:
            continue
        m = MARGIN[a.vital]
        reason = f"{_ADJ_NAME[a.vital]} danger {a.bound} limit {a.value:g}: {(a.rule_id or 'context').replace('_', ' ')}"
        if a.bound == "high" and (rng.danger_high is None or a.value < rng.danger_high):
            rng.danger_high = a.value
            if rng.safe_high is not None:
                rng.safe_high = round(min(rng.safe_high, a.value - m), 1)
        elif a.bound == "low" and (rng.danger_low is None or a.value > rng.danger_low):
            rng.danger_low = a.value
            if rng.safe_low is not None:
                rng.safe_low = round(max(rng.safe_low, a.value + m), 1)
        else:
            continue
        rng.reasons = [*(rng.reasons or []), reason]
    return out


def _vital_range(vital: str, low: float | None, high: float | None, reasons: list[str]) -> VitalRange:
    d_low, d_high = DANGER[vital]
    low = None if low is None else round(low, 1)
    high = None if high is None else round(high, 1)
    return VitalRange(safe_low=low, safe_high=high, danger_low=d_low, danger_high=d_high,
                      source="population", reasons=reasons)


def score0_ranges(patient_id: str | None = None) -> PatientRanges:
    """Fixed NEWS2 bands: score-0 range as safe, score-3 edges as danger."""
    return PatientRanges(patient_id=patient_id, **{
        v: _vital_range(v, *clamp_safe(v, *SCORE0[v]), []) for v in SCORE0})


def _intersect(vital: str, low: float, high: float, reasons: list[str]) -> tuple[float, float]:
    """Fitted band ∩ NEWS2 score-0. If that leaves less than the vital's minimum width, use score-0."""
    s_low, s_high = SCORE0[vital]
    lo, hi = max(low, s_low), min(high, s_high)
    if hi - lo < MIN_WIDTH[vital]:
        reasons.append("fitted range too narrow: using the NEWS2 normal range")
        return s_low, s_high
    return lo, hi


def features_from_context(ctx: PatientContext, rf: RangesFile) -> tuple[dict[str, float], list[str]]:
    """Feature values for the fit, clamped to the training range. Second item lists fallbacks used."""
    notes, clamp = [], rf.feature_clamp or {}
    means = rf.cohort_means or {}

    age = ctx.age
    if age is None:
        age = means.get("age")
        notes.append("age missing: used the survey average")
    if age is not None and "age" in clamp:
        age = min(max(age, clamp["age"][0]), clamp["age"][1])

    bmi = ctx.bmi
    if bmi is None and ctx.height_cm and ctx.weight_kg:
        bmi = ctx.weight_kg / (ctx.height_cm / 100) ** 2
    if bmi is None:
        bmi = means.get("bmi")
        notes.append("BMI missing: used the survey average")
    if bmi is not None and "bmi" in clamp:
        bmi = min(max(bmi, clamp["bmi"][0]), clamp["bmi"][1])

    if ctx.sex is None:
        notes.append("sex missing: used the average of both")
    if ctx.pregnant:
        notes.append("pregnancy not modelled")

    conditions, classes = set(ctx.conditions or []), set(ctx.drug_classes or [])
    feats = {"age": age, "age_sq": None if age is None else age * age,
             "male": 0.5 if ctx.sex is None else float(ctx.sex == "male"), "bmi": bmi}
    for name in rf.features or []:
        if name not in _FLAG_FEATURES_SKIP:
            feats[name] = float(name in conditions or name in classes)
    # a feature with no value contributes nothing rather than failing the intake
    return {k: v for k, v in feats.items() if v is not None}, notes


def _predict(fit, feats: dict[str, float]) -> float:
    return fit.intercept + sum(c * feats.get(n, 0.0) for n, c in (fit.coef or {}).items())


def _fitted_band(target, feats) -> tuple[float, float, float]:
    """Sorted 2.5th, 50th, 97.5th predictions so the quantiles never cross."""
    lo, mid, hi = sorted(_predict(f, feats) for f in (target.q025, target.q50, target.q975))
    return lo, mid, hi


def _shift_reasons(vital: str, target, feats: dict[str, float], rf: RangesFile) -> list[str]:
    """Typical-value change from each active flag (its median-fit coefficient), largest first."""
    out = []
    for name in rf.features or []:
        if name in _FLAG_FEATURES_SKIP or not feats.get(name):
            continue
        shift = target.q50.coef.get(name, 0.0)
        if abs(shift) >= MIN_SHIFT[vital]:
            word = "lower" if shift < 0 else "higher"
            label = _LABEL.get(name, name.replace("_", " "))
            out.append((abs(shift), f"typical {_NAME[vital]} {abs(shift):.0f} {_UNIT[vital]} {word}: {label}"))
    return [r for _, r in sorted(out, reverse=True)[:3]]


def build_population_ranges(ctx: PatientContext | None, rf: RangesFile | None = None
                            ) -> PatientRanges:
    """Population I8 for one patient. With no context or no ranges.json, the plain NEWS2 bands."""
    rf = rf if rf is not None else load_ranges()
    pid = ctx.patient_id if ctx else None
    if ctx is None or rf is None or not rf.targets:
        return score0_ranges(pid)

    feats, notes = features_from_context(ctx, rf)
    out: dict[str, VitalRange] = {}
    for vital in ("hr", "sbp"):
        target = rf.targets.get(vital)
        if target is None:
            out[vital] = _vital_range(vital, *clamp_safe(vital, *SCORE0[vital]), [])
            continue
        reasons = _shift_reasons(vital, target, feats, rf)
        low, _, high = _fitted_band(target, feats)
        low, high = _intersect(vital, low, high, reasons)
        out[vital] = _vital_range(vital, *clamp_safe(vital, low, high), reasons + notes)

    ref = (rf.reference or {})
    out["resp_rate"] = _vital_range("resp_rate", *clamp_safe("resp_rate", *SCORE0["resp_rate"]), [])
    out["spo2"] = _vital_range("spo2", *clamp_safe("spo2", *SCORE0["spo2"]), [])
    t = ref.get("temp_c")
    if isinstance(t, TempReference) and t.safe_low is not None and t.safe_high is not None:
        age = feats.get("age")
        shift = 0.0 if age is None or t.ref_age is None else (t.shift_per_decade or 0) * (age - t.ref_age) / 10
        reasons = []
        if abs(shift) >= MIN_SHIFT["temp_c"]:
            reasons.append(f"typical temperature {abs(shift):.1f} C {'lower' if shift < 0 else 'higher'}: age")
        low, high = _intersect("temp_c", t.safe_low + shift, t.safe_high + shift, reasons)
        out["temp_c"] = _vital_range("temp_c", *clamp_safe("temp_c", low, high), reasons)
    else:
        out["temp_c"] = _vital_range("temp_c", *clamp_safe("temp_c", *SCORE0["temp_c"]), [])
    return PatientRanges(patient_id=pid, **out)


def population_centres(ctx: PatientContext | None, rf: RangesFile | None = None) -> dict[str, float]:
    """Predicted typical resting value per personalized vital (mu0 for the personal baseline)."""
    rf = rf if rf is not None else load_ranges()
    centres = {"resp_rate": 16.0, "hr": 70.0}
    if ctx is not None and rf is not None and rf.targets and rf.targets.get("hr"):
        feats, _ = features_from_context(ctx, rf)
        _, mid, _ = _fitted_band(rf.targets["hr"], feats)
        centres["hr"] = min(max(mid, SCORE0["hr"][0]), SCORE0["hr"][1])
    return centres
