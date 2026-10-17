"""Replay fixtures through the risk engine and print what happens.
Use when checking the engine on eICU stays (intake from the stays file) or the synthetic wearer.
Usage:
  uv run python -m scripts.replay_fixture [stay_id] [--no-intake] [--out path.jsonl]
  uv run python -m scripts.replay_fixture --wearer
--out writes the I9 rows; it is never written by default, so fixtures/eicu_i9.jsonl (the recorded
stand-in used by alert logic and the Fetch.ai agent) is only replaced when asked for."""
import argparse
from pathlib import Path

from backend.contracts import PatientContext
from backend.fixtures import DIR, iter_i13, load_context, load_i6, load_stays, stay_rows
from backend.risk_engine.engine import RiskEngine


def replay_stays(only, intake, out):
    rows, eng, i9_out = load_i6(), RiskEngine(), []
    for stay in load_stays():
        pid = stay["patient_id"]
        if only and only != pid:
            continue
        if intake:
            eng.on_intake(PatientContext(patient_id=pid, age=stay.get("age"), sex=stay.get("sex")))
        srows = stay_rows(rows, pid)
        by_ts = {r.minute_ts: r for r in srows}
        path, levels, first_personal = [], {}, None
        for w in iter_i13(srows):  # no sleeping: fast-forwarded
            i14 = eng.on_second(w)
            if w.window_end_ts in by_ts:
                i9 = eng.on_minute(by_ts[w.window_end_ts])
                i9_out.append(i9.model_dump_json())
                levels[i9.level] = levels.get(i9.level, 0) + 1
                path.append(i14.news2)
                cur = eng.ranges[pid]
                if first_personal is None and "personal" in (cur.hr.source, cur.resp_rate.source):
                    first_personal = w.window_end_ts
        peak = max((p for p in path if p is not None), default=None)
        print(pid, stay["outcome"], "levels", levels, "peak NEWS2", peak, "first personal band", first_personal)
        r = eng.ranges[pid]
        print(f"  HR safe {r.hr.safe_low}-{r.hr.safe_high} ({r.hr.source}), "
              f"breathing safe {r.resp_rate.safe_low}-{r.resp_rate.safe_high} ({r.resp_rate.source})")
    if out:
        Path(out).write_text("".join(l + "\n" for l in i9_out))
        print(f"wrote {len(i9_out)} I9 rows to {out}")


def replay_wearer():
    eng = RiskEngine()
    eng.on_intake(load_context())
    pop = eng.intake_ranges["demo-001"].hr
    print(f"population HR safe {pop.safe_low}-{pop.safe_high}  reasons: {pop.reasons}")
    for i, m in enumerate(load_i6(DIR / "wearer_drift_i6.jsonl")):
        res = eng.on_minute(m)
        hr = eng.ranges[m.patient_id].hr
        if i % 5 == 4:
            print(f"min {i + 1:2d} HR {m.hr:5.1f} band {hr.safe_low}-{hr.safe_high} ({hr.source}) -> {res.level}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stay", nargs="?")
    ap.add_argument("--no-intake", action="store_true", help="replay with no intake: plain NEWS2 bands")
    ap.add_argument("--wearer", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    replay_wearer() if a.wearer else replay_stays(a.stay, not a.no_intake, a.out)
