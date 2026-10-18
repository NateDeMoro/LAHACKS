"""Personal baseline (T3): narrows the safe band for heart rate and breathing toward the patient's
own readings. Use when updating I8 each period from I6.

Only the safe band moves, and only inward: the result stays inside the population safe band, danger
edges are untouched, and a vital that scores NEWS2 points on arrival is never learned. Windows are
counted in time from period_ts, so 5-minute eICU rows and 30 s live rows behave alike."""
from statistics import median

from backend.contracts import BaselineConfig, PeriodSummary, PatientRanges, VitalRange
from backend.risk_engine import news2

VITALS = ("hr", "resp_rate")
_POINTS = {"hr": news2.score_hr, "resp_rate": news2.score_rr}
_MAD_TO_SD = 1.4826  # robust standard deviation from the median absolute deviation
_BAND_SD = 3.92      # a 95% band is 3.92 standard deviations wide


def is_clean_period(clean_seconds: int | None, min_clean_seconds: int | None) -> bool:
    """A period counts if clean_seconds is unknown or at least the minimum. Shared with trend.py."""
    return clean_seconds is None or clean_seconds >= (min_clean_seconds or 0)


class _VitalBaseline:
    def __init__(self, vital: str, pop: VitalRange, mu0: float, cfg: BaselineConfig):
        self.vital, self.pop, self.mu0, self.cfg = vital, pop, mu0, cfg
        self.samples: list[tuple[float, float]] = []  # (minutes since first clean sample, value)
        self.t0 = None
        self.status, self.why = "learning", ""  # status: learning | frozen | skipped
        self.range = pop

    def rebase(self, pop: VitalRange, mu0: float):
        """Take a new population range (a later intake) and refit from the samples already seen."""
        self.pop, self.mu0, self.range = pop, mu0, pop
        if self.status == "skipped":
            self._skip(self.why)
        elif len(self.samples) >= 3 and self.samples[-1][0] >= self.cfg.min_minutes:
            self._fit(self.samples[-1][0])

    def _skip(self, why: str) -> bool:
        self.status, self.why = "skipped", why
        self.range = self.pop.model_copy(update={"reasons": [*(self.pop.reasons or []), why]})
        return True

    def update(self, ts, value: float) -> bool:
        """Add one clean reading; returns True when the current range changed."""
        if self.status != "learning":
            return False
        if self.t0 is None:
            self.t0 = ts
        elapsed = (ts - self.t0).total_seconds() / 60
        if elapsed <= self.cfg.arrival_check_minutes and _POINTS[self.vital](value) > 0:
            return self._skip("no personal baseline: abnormal on arrival")
        self.samples.append((elapsed, value))
        if elapsed < self.cfg.min_minutes or len(self.samples) < 3:
            return False
        changed = self._fit(elapsed)
        if elapsed >= self.cfg.learn_minutes and self.status == "learning":
            self.status = "frozen"
        return changed

    def _fit(self, elapsed: float) -> bool:
        cfg, pop, v = self.cfg, self.pop, self.vital
        values = [x for _, x in self.samples]
        med = median(values)
        if not pop.safe_low <= med <= pop.safe_high:
            return self._skip("no personal baseline: own level outside the typical range")
        sigma = max(_MAD_TO_SD * median(abs(x - med) for x in values), cfg.spread_floor[v])
        tau = (pop.safe_high - pop.safe_low) / _BAND_SD  # how much people differ from each other
        n0 = min(max(sigma ** 2 / tau ** 2, cfg.n0_min), cfg.n0_max)
        gaps = sorted(b[0] - a[0] for a, b in zip(self.samples, self.samples[1:]))
        n = len(values) * median(gaps)  # minutes of data: 5-minute rows count 5 each, 30 s rows 0.5
        centre = (n0 * self.mu0 + n * med) / (n0 + n)
        half = cfg.k * sigma * (1 + 1 / (n0 + n)) ** 0.5
        low, high = min(centre - half, med), max(centre + half, med)
        if high - low < cfg.min_width[v]:
            mid = (low + high) / 2
            low, high = mid - cfg.min_width[v] / 2, mid + cfg.min_width[v] / 2
        low, high = max(low, pop.safe_low), min(high, pop.safe_high)
        if (low, high) == (pop.safe_low, pop.safe_high):
            changed = self.range != pop  # a refit as wide as the population band drops an earlier narrow one
            self.range = pop
            return changed
        new = pop.model_copy(update={
            "safe_low": round(low, 1), "safe_high": round(high, 1), "source": "personal",
            "reasons": [*(pop.reasons or []), f"narrowed to your readings over {elapsed:.0f} min"]})
        changed = new != self.range
        self.range = new
        return changed


class PersonalBaseline:
    def __init__(self, cfg: BaselineConfig, population: PatientRanges, centres: dict[str, float]):
        self.population = population
        self.vitals = {v: _VitalBaseline(v, getattr(population, v), centres[v], cfg) for v in VITALS}
        self.min_clean_seconds = cfg.min_clean_seconds or 0

    def rebase(self, population: PatientRanges, centres: dict[str, float]):
        """A later intake replaces the population ranges but keeps what was learned so far."""
        self.population = population
        for v, b in self.vitals.items():
            b.rebase(getattr(population, v), centres[v])

    def update(self, m: PeriodSummary) -> bool:
        """Feed one I6 row; returns True when the ranges changed."""
        if m.period_ts is None or not is_clean_period(m.clean_seconds, self.min_clean_seconds):
            return False
        changed = False
        for v in VITALS:
            value = getattr(m, v)
            if value is not None:
                changed |= self.vitals[v].update(m.period_ts, value)
        return changed

    @property
    def ranges(self) -> PatientRanges:
        return self.population.model_copy(update={v: b.range for v, b in self.vitals.items()})
