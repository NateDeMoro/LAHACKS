"""Sweep the personal-baseline settings (k, spread floors, min width) over eICU and print comparison tables.
Use when choosing k and the spread floors.

Population: stays with >= 6 h (72 rows) of rows having both heart rate and breathing; only the first 4 h
of each stay is replayed through a fresh RiskEngine (no intake, plain NEWS2 bands). A flag is any minute
whose I9 level is not safe. 'population only' never builds a personal band, so it is the reference.

Data: eICU Collaborative Research Database (Pollard et al., PhysioNet), ODbL license.
Caveat: eICU values are 5-minute aggregates, so their spread is smaller than live 1-minute spread;
treat the spread-floor results as a lower bound on how often a live band would stay wide."""
import math
from statistics import median

from backend.contracts import BaselineConfig, PeriodSummary
from backend.risk_engine.engine import RiskEngine, load_config
from backend.timeutil import offset_to_ts
from scripts.build_eicu_fixtures import load_clean

MIN_ROWS, WINDOW_MIN = 72, 240
BASE = load_config()


def load_stays():
    vit, pat = load_clean()
    status = pat.set_index("patientunitstayid").hospitaldischargestatus
    vit = vit.dropna(subset=["heartrate", "respiration"])
    stays = []
    for stay, g in vit.groupby("patientunitstayid"):
        if len(g) < MIN_ROWS or status.get(stay) not in ("Alive", "Expired"):
            continue
        g = g[g.observationoffset <= g.observationoffset.iloc[0] + WINDOW_MIN]
        rows = [PeriodSummary(patient_id=f"eicu-{stay}", period_ts=offset_to_ts(o), hr=h, resp_rate=r)
                for o, h, r in zip(g.observationoffset, g.heartrate, g.respiration)]
        stays.append((status[stay], g.observationoffset.iloc[0], rows))
    return stays


def make_config(k, mult):
    b = BASE.baseline
    return BASE.model_copy(update={"baseline": b.model_copy(update={
        "k": k,
        "spread_floor": {v: x * mult for v, x in b.spread_floor.items()},
        "min_width": {v: x * mult for v, x in b.min_width.items()}})})


def run(cfg, stays):
    """Per-outcome lists of per-stay results: (flags, hours, first_flag_min or None, hr_personal, rr_personal)."""
    out = {"Alive": [], "Expired": []}
    for outcome, t0, rows in stays:
        eng = RiskEngine(cfg)
        flags, first = 0, None
        for m in rows:
            r = eng.on_period(m)
            if r.level != "safe" and r.vital in ("hr", "resp_rate"):
                flags += 1
                if first is None:
                    first = (m.period_ts - rows[0].period_ts).total_seconds() / 60
        rg = eng.ranges[rows[0].patient_id]
        hours = max((rows[-1].period_ts - rows[0].period_ts).total_seconds() / 3600, 1e-9)
        out[outcome].append((flags, hours, first, rg.hr.source == "personal", rg.resp_rate.source == "personal"))
    return out


def summarize(res):
    n = len(res)
    firsts = [x[2] for x in res if x[2] is not None]
    return {"rate": sum(x[0] for x in res) / sum(x[1] for x in res),
            "share": sum(x[0] > 0 for x in res) / n,
            "first": median(firsts) if firsts else math.nan,
            "hr_p": sum(x[3] for x in res) / n, "rr_p": sum(x[4] for x in res) / n}


def main():
    stays = load_stays()
    alive = sum(s[0] == "Alive" for s in stays)
    print(f"stays used: {len(stays)} (survivors {alive}, non-survivors {len(stays) - alive})\n")
    ref_cfg = BASE.model_copy(update={"baseline": BASE.baseline.model_copy(update={"min_minutes": 1e9})})
    settings = [("population only", ref_cfg)] + [
        (f"k={k} floor x{m}", make_config(k, m)) for k in (2.0, 2.5, 3.0) for m in (0.5, 1.0, 1.5)]
    results = {}
    for name, cfg in settings:
        res = run(cfg, stays)
        results[name] = {o: summarize(res[o]) for o in res}
    cols = [("flag rows/pt-h", "rate", "{:14.2f}"), ("pts flagged", "share", "{:11.1%}"),
            ("median min to 1st", "first", "{:17.0f}"), ("hr personal", "hr_p", "{:11.1%}"),
            ("rr personal", "rr_p", "{:11.1%}")]
    for outcome in ("Alive", "Expired"):
        print(f"{outcome}")
        print(f"{'setting':<20}" + " ".join(f"{c[0]:>{len(c[0])}}" for c in cols))
        for name, _ in settings:
            print(f"{name:<20}" + " ".join(f.format(results[name][outcome][key]) for _, key, f in cols))
        print()
    ref = results["population only"]
    print("Interpretation (relative to population only)")
    print(f"{'setting':<20}{'survivor false-alarm rate':>27}{'non-survivor flag share':>26}")
    for name, _ in settings[1:]:
        fa = results[name]["Alive"]["rate"] / ref["Alive"]["rate"]
        sh = results[name]["Expired"]["share"] / ref["Expired"]["share"]
        print(f"{name:<20}{fa:>26.2f}x{sh:>25.2f}x")
    print("Lower survivor rate with non-survivor share near 1.0x is better: fewer false alarms, same catches.")


if __name__ == "__main__":
    main()
