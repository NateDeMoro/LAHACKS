"""Fit HR and systolic BP population bands (linear quantile regression) and write models/ranges.json.

Sources: NHANES 2017-March 2020 files P_DEMO, P_BPXO, P_BMX, P_DIQ, P_MCQ, P_BPQ, P_RXQ_RX from
https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/ and the drug lookup RXQ_DRUG from
https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/1988/DataFiles/RXQ_DRUG.xpt

The fit is unweighted: statsmodels QuantReg has no weights option, and a model conditioned on
features does not need survey weights for the conditional quantiles.

Use when refitting the HR/SBP population bands.
"""
import json
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from backend.contracts import RangesFile

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "nhanes"
BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/"
FILES = {f"P_{n}.XPT": BASE + f"2017/DataFiles/P_{n}.XPT" for n in ["DEMO", "BPXO", "BMX", "DIQ", "MCQ", "BPQ", "RXQ_RX"]}
FILES["RXQ_DRUG.xpt"] = BASE + "1988/DataFiles/RXQ_DRUG.xpt"
QS = {"q025": 0.025, "q50": 0.5, "q975": 0.975}
MIN_USERS = 300
CONDITIONS = {"hypertension": ["BPQ020"], "diabetes": ["DIQ010"], "asthma": ["MCQ010"], "copd": ["MCQ160P"],
              "cancer": ["MCQ220"], "thyroid": ["MCQ160M"], "liver": ["MCQ160L"],
              "heart_disease": ["MCQ160C", "MCQ160D", "MCQ160E"], "stroke": ["MCQ160F"], "heart_failure": ["MCQ160B"]}
DRUG_CLASSES = {"beta_blocker": {47, 472}, "ssri": {208}, "snri": {308}}
FLAGS = list(CONDITIONS) + list(DRUG_CLASSES)
FEATURES = ["age", "age_sq", "male", "bmi"] + FLAGS


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        dest = RAW / name
        if dest.exists():
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"})
        part = dest.with_name(name + ".part")
        with urllib.request.urlopen(req) as r, open(part, "wb") as f:
            f.write(r.read())
        part.rename(dest)


def load(name):
    return pd.read_sas(RAW / name, format="xport", encoding="latin1")


def build_cohort():
    df = load("P_DEMO.XPT")[["SEQN", "RIDAGEYR", "RIAGENDR", "RIDEXPRG"]]
    for name in ["P_BPXO.XPT", "P_BMX.XPT", "P_DIQ.XPT", "P_MCQ.XPT", "P_BPQ.XPT"]:
        df = df.merge(load(name), on="SEQN", how="left", suffixes=("", "_dup"))
    pls = df[["BPXOPLS1", "BPXOPLS2", "BPXOPLS3"]]
    sy = df[["BPXOSY1", "BPXOSY2", "BPXOSY3"]]
    df["hr"] = pls.mean(axis=1).where(pls.notna().sum(axis=1) >= 2)
    df["sbp"] = sy.mean(axis=1).where(sy.notna().sum(axis=1) >= 2)
    df = df[(df.RIDAGEYR >= 18) & (df.RIDEXPRG != 1) & df.hr.notna()].copy()

    df["age"] = df.RIDAGEYR.clip(18, 80)
    df["age_sq"] = df.age ** 2
    df["male"] = (df.RIAGENDR == 1).astype(int)
    df["bmi"] = df.BMXBMI.fillna(df.BMXBMI.mean())
    # blank, 7 (refused) and 9 (don't know) all fall through to 0
    for flag, cols in CONDITIONS.items():
        df[flag] = (df[cols] == 1).any(axis=1).astype(int)

    rx = load("P_RXQ_RX.XPT")[["SEQN", "RXDDRGID"]].dropna()
    drug = load("RXQ_DRUG.xpt")
    # category level columns A/B/C across 4 slots: 47 sits at level B, 472/208/308 at level C
    cat_cols = [f"RXDDCI{i}{l}" for i in range(1, 5) for l in "ABC"]
    rx = rx.merge(drug[["RXDDRGID"] + cat_cols], on="RXDDRGID", how="left")
    for flag, codes in DRUG_CLASSES.items():
        users = rx.loc[rx[cat_cols].isin(codes).any(axis=1), "SEQN"].unique()
        df[flag] = df.SEQN.isin(users).astype(int)
    return df


def fit_target(train, y, small_flags):
    d = train[train[y].notna()]
    X = sm.add_constant(d[FEATURES])
    fits = {}
    for key, q in QS.items():
        fits[key] = sm.QuantReg(d[y], X).fit(q=q, max_iter=5000).params.to_dict()
    for flag in small_flags:
        fits["q025"][flag] = fits["q975"][flag] = fits["q50"][flag]
    return fits


def predict(fits, df):
    X = sm.add_constant(df[FEATURES], has_constant="add")
    p = np.column_stack([X @ pd.Series(fits[k]).reindex(X.columns) for k in QS])
    return np.sort(p, axis=1)


if __name__ == "__main__":
    download()
    df = build_cohort()
    counts = {f: int(df[f].sum()) for f in FLAGS}
    small_flags = [f for f, n in counts.items() if n < MIN_USERS]
    print(f"cohort n={len(df)}  sbp n={df.sbp.notna().sum()}")
    print("flag users:", counts)
    print("small-group rule applied to:", small_flags)

    shuffled = df.sample(frac=1, random_state=0)
    n_train = int(len(df) * 0.8)
    train, hold = shuffled.iloc[:n_train], shuffled.iloc[n_train:]

    bb = df.beta_blocker == 1
    print(f"median HR beta-blocker (n={bb.sum()}): {df.hr[bb].median():.1f}  non-users (n={(~bb).sum()}): {df.hr[~bb].median():.1f}")

    subgroups = {"overall": slice(None), "beta_blocker": hold.beta_blocker == 1, "bmi40": hold.bmi >= 40, "age70": hold.age >= 70}
    targets, coverage = {}, {}
    for y in ["hr", "sbp"]:
        fits = fit_target(train, y, small_flags)
        targets[y] = {k: {"intercept": v["const"], "coef": {f: v[f] for f in FEATURES}} for k, v in fits.items()}
        h = hold[hold[y].notna()]
        p = predict(fits, h)
        inside = pd.Series((h[y].values >= p[:, 0]) & (h[y].values <= p[:, 2]), index=h.index)
        for name, mask in subgroups.items():
            m = mask if isinstance(mask, slice) else mask.reindex(h.index, fill_value=False)
            sel = inside[m]
            coverage[f"{y}_{name}"] = float(sel.mean())
            print(f"{y}_{name}: coverage {sel.mean():.3f} (n={len(sel)})")

    lo, hi = df.bmi.quantile([0.01, 0.99])
    data = {
        "meta": {"cycle": "NHANES 2017-March 2020", "n_train": len(train), "n_holdout": len(hold),
                 "fit_date": date.today().isoformat(), "coverage": coverage,
                 "notes": "Dropped features: tricyclics (87 users, too few) and BP-medication flag (no I4 field). "
                          f"Binary flags with <{MIN_USERS} users use their q50 coefficient for all quantiles: {', '.join(small_flags)}."},
        "features": FEATURES,
        "feature_clamp": {"age": [18, 80], "bmi": [float(lo), float(hi)]},
        "cohort_means": {"age": float(df.age.mean()), "bmi": float(df.bmi.mean())},
        "targets": targets,
        "reference": {"resp_rate": {"safe_low": 12, "safe_high": 20}, "spo2": {"safe_low": 96, "safe_high": 100},
                      "temp_c": {"safe_low": 35.7, "safe_high": 37.3, "ref_age": 53, "shift_per_decade": -0.021}},
    }
    RangesFile(**data)
    (ROOT / "models" / "ranges.json").write_text(json.dumps(data, indent=2))
    print("wrote models/ranges.json")
