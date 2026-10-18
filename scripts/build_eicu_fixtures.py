"""Build I6 fixtures from the eICU Collaborative Research Database demo (v2.0.1).

Source: https://physionet.org/content/eicu-crd-demo/2.0.1/ (open access, ODbL).
Attribution: Pollard et al., eICU-CRD, PhysioNet. Raw files stay in data/raw (gitignored);
only the selected-stay outputs in fixtures/ are committed.
Use when regenerating eICU stand-in rows for the risk engine, alert logic or Fetch.ai agent.
"""
import json
import urllib.request
from pathlib import Path

import pandas as pd

from backend.risk_engine import news2
from backend.timeutil import offset_to_ts

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "fixtures"
BASE = "https://physionet.org/files/eicu-crd-demo/2.0.1/"
LIMITS = {"heartrate": (20, 250), "respiration": (3, 60), "sao2": (50, 100), "temperature": (30, 43)}
WINDOW_MIN = 24 * 60  # keep the last 24 h of each stay
MIN_OBS = 72          # 6 h of 5-minute rows with HR, RR and SpO2 all present
PER_OUTCOME = 3


def fetch(name: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    if not path.exists():
        part = path.with_suffix(".part")
        urllib.request.urlretrieve(BASE + name, part)
        part.rename(path)
    return path


def partial_news2(r) -> int:
    total, _ = news2.score(resp_rate=_n(r.respiration), spo2=_n(r.sao2), hr=_n(r.heartrate),
                           temp_c=_n(r.temperature))
    return total or 0


def _n(v):
    return None if pd.isna(v) else float(v)


def load_clean():
    """Cleaned eICU vitals (implausible values nulled, sorted by stay and offset) and the patient table.
    Use when a script needs the raw eICU stays, e.g. fixtures or training/tune_baseline.py."""
    vit = pd.read_csv(fetch("vitalPeriodic.csv.gz"),
                      usecols=["patientunitstayid", "observationoffset", *LIMITS])
    pat = pd.read_csv(fetch("patient.csv.gz"),
                      usecols=["patientunitstayid", "gender", "age", "hospitaldischargestatus"])
    for col, (lo, hi) in LIMITS.items():
        vit.loc[(vit[col] < lo) | (vit[col] > hi), col] = None
    return vit.sort_values(["patientunitstayid", "observationoffset"]), pat


def main():
    vit, pat = load_clean()

    cands = []
    for stay, g in vit.groupby("patientunitstayid"):
        last = g.observationoffset.max()
        g = g[g.observationoffset >= last - WINDOW_MIN]
        full = g.dropna(subset=["heartrate", "respiration", "sao2"])
        if len(full) < MIN_OBS:
            continue
        cands.append((stay, g, max(partial_news2(r) for r in g.itertuples())))
    status = pat.set_index("patientunitstayid").hospitaldischargestatus
    chosen = []
    for outcome in ("Expired", "Alive"):
        pool = sorted((c for c in cands if status.get(c[0]) == outcome), key=lambda c: -c[2])
        # highest-scoring first, then spread across the rest
        picks = pool[:1] + pool[1:][:: max(1, len(pool) // PER_OUTCOME)][: PER_OUTCOME - 1]
        chosen += [(c, outcome) for c in picks]

    # one extra survivor that starts normal (HR and breathing score 0 for the first hour), so the
    # personal baseline has a stay it can learn from; the ICU stays above mostly start abnormal
    def starts_normal(g):
        first = g.head(12)
        return len(first.dropna(subset=["heartrate", "respiration"])) == 12 and all(
            news2.score_hr(r.heartrate) == 0 and news2.score_rr(r.respiration) == 0 for r in first.itertuples())
    normal = [c for c in cands if status.get(c[0]) == "Alive" and starts_normal(c[1])
              and c[0] not in {x[0][0] for x in chosen}]
    if normal:
        chosen.append((min(normal, key=lambda c: c[2]), "Alive"))

    i6, stays = [], []
    for (stay, g, peak), outcome in chosen:
        pid = f"eicu-{stay}"
        for r in g.itertuples():
            row = dict(patient_id=pid, period_ts=offset_to_ts(r.observationoffset).isoformat(),
                       hr=_n(r.heartrate), resp_rate=_n(r.respiration), spo2=_n(r.sao2),
                       temp_c=_n(r.temperature), clean_seconds=None)
            if any(row[k] is not None for k in ("hr", "resp_rate", "spo2", "temp_c")):
                i6.append(row)
        p = pat[pat.patientunitstayid == stay].iloc[0]
        age = str(p.age).replace("> ", "")
        stays.append(dict(patient_id=pid, age=int(age) if age.isdigit() else None,
                          sex={"Male": "male", "Female": "female"}.get(p.gender),
                          outcome=outcome.lower(), peak_partial_news2=peak))
    OUT.mkdir(exist_ok=True)
    (OUT / "eicu_i6.jsonl").write_text("".join(json.dumps(r) + "\n" for r in i6))
    (OUT / "eicu_stays.json").write_text(json.dumps(stays, indent=2) + "\n")
    print(f"{len(stays)} stays, {len(i6)} I6 rows")
    for s in stays:
        print(s)


if __name__ == "__main__":
    main()
