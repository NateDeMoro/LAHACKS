import pytest

from backend.contracts import (BaselineConfig, QuantileFit, RangesFile,
                               ReferenceBand, TargetFit, TempReference)
from backend.risk_engine.ranges import score0_ranges

def _q(intercept, **coef):
    return QuantileFit(intercept=intercept, coef=coef)


@pytest.fixture
def rf():
    """Synthetic fit: HR 45-95 around 70 (beta-blocker -6 on the median), SBP 100-150."""
    hr = TargetFit(q025=_q(45, beta_blocker=-6), q50=_q(70, beta_blocker=-6), q975=_q(95, beta_blocker=-6))
    sbp = TargetFit(q025=_q(100), q50=_q(122), q975=_q(150))
    return RangesFile(
        features=["age", "age_sq", "male", "bmi", "beta_blocker"], feature_clamp={"age": [18, 80], "bmi": [15, 50]},
        cohort_means={"age": 45, "bmi": 28}, targets={"hr": hr, "sbp": sbp},
        reference={"resp_rate": ReferenceBand(safe_low=12, safe_high=20),
                   "spo2": ReferenceBand(safe_low=96, safe_high=100),
                   "temp_c": TempReference(safe_low=35.7, safe_high=37.3, ref_age=53, shift_per_decade=-0.021)})


@pytest.fixture
def cfg():
    return BaselineConfig()  # the shipped defaults


@pytest.fixture
def pop():
    return score0_ranges("p")
