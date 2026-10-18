"""Sweep alert-logic persistence windows over eICU and print comparison tables.
Use when choosing the AlertConfig windows in models/config.json.

Population: stays with >= 6 h (72 rows) having heart rate and breathing, outcome Alive or Expired. Each
stay's first 24 h is run once through a fresh RiskEngine (intake from age and sex; on_second once per row,
not every second) and the I9 rows are cached, so a sweep only reruns alert logic. Policy: every alert is
acknowledged 10 minutes after it fires. 'Episodes' are new alerts (resolved updates are not counted).

Caveats: eICU rows are 5 minutes apart, so windows under 5 min cannot be told apart here (0 is
immediate; anything from 1 to 5 behaves like 5); those are set at C2 on the real strap. The trend
trigger is never exercised (no fast model on eICU), and ICU patients alert far more than a waiting room.

Usage: uv run python -m training.tune_alerts [--refresh]
Data: eICU Collaborative Research Database (Pollard et al., PhysioNet), ODbL license."""
import argparse
import pickle
from datetime import timedelta
from statistics import median

from backend.contracts import (Acknowledgment, AlertConfig, LiveWindow, MinuteSummary, PatientContext,
                               RiskResult)
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine, load_config
from backend.timeutil import offset_to_ts
from scripts.build_eicu_fixtures import ROOT, load_clean

CACHE = ROOT / "data" / "cache" / "tune_alerts_i9.pkl"
MIN_ROWS, WINDOW_MIN, ACK_AFTER = 72, 24 * 60, timedelta(minutes=10)
WINDOWS = (0, 5, 10, 15)
TRIGGERS = ("warning_persisted_minutes", "vital_danger_minutes", "news2_total_minutes")


def _n(v):
    return None if v != v else float(v)


def build_i9():
    """[(outcome, [I9 ...])] per usable stay, first 24 h, engine run once per stay."""
    vit, pat = load_clean()
    pat = pat.set_index("patientunitstayid")
    cfg, stays = load_config(), []
    for stay, g in vit.groupby("patientunitstayid"):
        outcome = pat.hospitaldischargestatus.get(stay)
        if outcome not in ("Alive", "Expired") or len(g.dropna(subset=["heartrate", "respiration"])) < MIN_ROWS:
            continue
        g = g[g.observationoffset <= g.observationoffset.iloc[0] + WINDOW_MIN]
        age = str(pat.age[stay]).replace("> ", "")
        pid = f"eicu-{stay}"
        eng = RiskEngine(cfg)
        eng.on_intake(PatientContext(patient_id=pid, age=int(age) if age.isdigit() else None,
                                     sex={"Male": "male", "Female": "female"}.get(pat.gender[stay])))
        out = []
        for r in g.itertuples():
            ts = offset_to_ts(r.observationoffset)
            vals = dict(hr=_n(r.heartrate), resp_rate=_n(r.respiration), spo2=_n(r.sao2), temp_c=_n(r.temperature))
            if all(v is None for v in vals.values()):
                continue
            eng.on_second(LiveWindow(patient_id=pid, window_end_ts=ts, **vals))
            out.append(eng.on_minute(MinuteSummary(patient_id=pid, minute_ts=ts, **vals)))
        stays.append((outcome, out))
    return stays


def load_i9(refresh):
    if CACHE.exists() and not refresh:
        return pickle.loads(CACHE.read_bytes())
    stays = build_i9()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(stays))
    return stays


def run_alerts(cfg: AlertConfig, rows: list[RiskResult]):
    """Alert logic over one stay with the ack-after-10-min policy. Returns (new alerts by trigger, first alert minutes)."""
    lg, pending, counts, first = AlertLogic(cfg), [], {}, None
    for r in rows:
        for a in [a for a in pending if a.ts <= r.ts]:
            lg.on_ack(a)
        pending = [a for a in pending if a.ts > r.ts]
        for e in lg.on_risk(r):
            if e.resolved:
                continue
            counts[e.trigger] = counts.get(e.trigger, 0) + 1
            pending.append(Acknowledgment(alert_id=e.alert_id, ts=e.ts + ACK_AFTER))
            if first is None:
                first = (e.ts - rows[0].ts).total_seconds() / 60
    return counts, first


def evaluate(cfg, stays):
    """Survivor episodes per patient-hour (total and by trigger), non-survivor median minutes to the first alert."""
    surv = {"hours": 0.0, "n": 0}
    by_trig, firsts, exp_n, exp_alerted = {}, [], 0, 0
    for outcome, rows in stays:
        counts, first = run_alerts(cfg, rows)
        if outcome == "Alive":
            surv["hours"] += (rows[-1].ts - rows[0].ts).total_seconds() / 3600
            for k, v in counts.items():
                by_trig[k] = by_trig.get(k, 0) + v
        else:
            exp_n += 1
            if first is not None:
                firsts.append(first)
                exp_alerted += 1
    h = surv["hours"]
    return {"rate": sum(by_trig.values()) / h, "by": {k: v / h for k, v in by_trig.items()},
            "first": median(firsts) if firsts else float("nan"), "share": exp_alerted / max(exp_n, 1)}


def row_text(label, res):
    b = res["by"]
    return (f"{label:<26}{res['rate']:>10.3f}{b.get('warning_persisted', 0):>10.3f}{b.get('vital_danger', 0):>10.3f}"
            f"{b.get('news2_total', 0):>10.3f}{res['first']:>12.0f}{res['share']:>10.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="rerun the engine instead of using the cached I9")
    stays = load_i9(ap.parse_args().refresh)
    alive = sum(o == "Alive" for o, _ in stays)
    print(f"stays used: {len(stays)} (survivors {alive}, non-survivors {len(stays) - alive}); ack-after-10-min policy")
    print("Windows under 5 min cannot be resolved on eICU's 5-minute rows; set at C2.\n")
    head = (f"{'setting':<26}{'surv ep/h':>10}{'warning':>10}{'danger':>10}{'news2':>10}"
            f"{'nonsurv 1st':>12}{'alerted':>10}")
    base = load_config().alerts or AlertConfig()

    print("All windows together")
    print(head)
    for w in WINDOWS:
        cfg = base.model_copy(update={k: w for k in (*TRIGGERS, "trend_minutes")})
        print(row_text(f"all = {w} min", evaluate(cfg, stays)))

    for trig in TRIGGERS:
        print(f"\n{trig} varied, other windows at {base.warning_persisted_minutes:g}/"
              f"{base.vital_danger_minutes:g}/{base.news2_total_minutes:g}")
        print(head)
        for w in WINDOWS:
            print(row_text(f"{trig.removesuffix('_minutes')} = {w}",
                           evaluate(base.model_copy(update={trig: w}), stays)))


if __name__ == "__main__":
    main()
