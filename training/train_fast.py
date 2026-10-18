"""T6 fast trend model: label report, baselines, LightGBM training and evaluation on MIMIC-III numerics.
Use when reproducing the fast-model numbers or regenerating models/fast_15.txt.

  python -m training.train_fast report   # cleaning counts, positives per vital, 20 positive examples (no training)
  python -m training.train_fast train    # features, baselines, 5-fold CV, held-out test, ship rule, outputs

Alert = score >= cutoff with a 15-minute refractory period. Rates are per monitored patient-hour (all minutes from
each segment's 15th observed minute). Cutoffs are matched on training patients to the alert rate of partial
NEWS2 >= 5 (HR, breathing, SpO2, plus non-invasive systolic where recorded). Held-out patients are scored once.
"""
import argparse
import json
import logging
import math
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from backend.risk_engine import fast_features as ff
from backend.risk_engine import news2
from training.fast_labels import HORIZON, label_segment
from training.mimic_numerics import VITALS, load_segments

log = logging.getLogger("train_fast")
ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"
REFRACTORY, LOOKBACK, SBP_HOLD = 15, 60, 30
SEED, N_BOOT, HELD_OUT_FRAC, N_FOLDS = 0, 1000, 0.2, 5


# ---------- rows ----------
def _news2_table(fn, hi):
    return np.array([fn(float(i)) for i in range(hi + 1)])


def partial_news2(seg) -> np.ndarray:
    """Per-minute partial NEWS2 total from HR, breathing, SpO2 and the last NBP systolic held 30 minutes."""
    tabs = {"hr": _news2_table(news2.score_hr, 260), "resp_rate": _news2_table(news2.score_rr, 70),
            "spo2": _news2_table(news2.score_spo2, 105), "sbp": _news2_table(news2.score_sbp, 320)}
    sbp = pd.Series(seg.sbp).ffill(limit=SBP_HOLD).to_numpy()
    total = np.zeros(len(seg))
    for name, x in (("hr", seg.hr), ("resp_rate", seg.resp_rate), ("spo2", seg.spo2), ("sbp", sbp)):
        ok = np.isfinite(x)
        idx = np.floor(np.where(ok, x, 0) + 0.5).astype(int)
        total += np.where(ok, tabs[name][np.clip(idx, 0, len(tabs[name]) - 1)], 0)
    return total


def segment_rows(args):
    sid, seg = args
    lab = label_segment(seg)
    t = np.arange(len(seg), dtype=float)
    cols = {"hr": seg.hr, "resp_rate": seg.resp_rate, "spo2": seg.spo2}
    recs = []
    for i in np.nonzero(lab.live_row)[0]:
        lo = max(0, i - 29)
        f = ff.compute_features({v: (t[lo:i + 1], cols[v][lo:i + 1]) for v in VITALS}, float(i))
        f.update(seg_id=sid, i=int(i), valid=bool(lab.valid[i]), label=int(lab.label[i]))
        for v in VITALS:
            f[f"pos_{v}"] = int(lab.pos_by_vital[v][i])
        recs.append(f)
    return sid, recs, lab.events, lab.first_row, partial_news2(seg)


def build(segments):
    cache = PROC / "fast_rows.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    PROC.mkdir(parents=True, exist_ok=True)
    rows, events, meta, ns = [], {}, {}, {}
    with ProcessPoolExecutor() as ex:
        for sid, recs, evs, first_row, n2 in ex.map(segment_rows, list(enumerate(segments)), chunksize=4):
            rows += recs
            events[sid], meta[sid], ns[sid] = evs, first_row, n2
    df = pd.DataFrame(rows)
    df["patient"] = [segments[s].patient for s in df.seg_id]
    out = (df, events, meta, ns)
    cache.write_bytes(pickle.dumps(out))
    return out


# ---------- alerts and metrics ----------
def alert_times(idx, ok) -> list:
    """idx: minute indices of candidate rows (sorted); ok: bool whether score >= cutoff. 15-minute refractory."""
    out, last = [], -10**9
    for i, o in zip(idx, ok):
        if o and i - last >= REFRACTORY:
            out.append(int(i))
            last = i
    return out


def news2_alerts(ns, first_row) -> int:
    idx = np.arange(first_row, len(ns))
    return len(alert_times(idx, ns[first_row:] >= 5))


def per_patient_stats(df, scores, cutoff, events, meta, segments, patients):
    """{patient: dict(n_events, warn, detected, hours, alerts, hourly_detect)} for the given score column."""
    stats = {p: dict(n_events=0, warn=0.0, detected=0, hours=0.0, alerts=0, hourly=0.0) for p in patients}
    pset = set(patients)
    for sid, g in df[df.patient.isin(pset)].groupby("seg_id"):
        p = segments[sid].patient
        s = scores[g.index]
        al = alert_times(g.i.to_numpy(), s >= cutoff)
        st = stats[p]
        st["alerts"] += len(al)
        al = np.array(al)
        for onset, end, _ in events[sid]:
            st["n_events"] += 1
            hit = al[(al >= onset - LOOKBACK) & (al < onset)] if len(al) else al
            if len(hit):
                st["detected"] += 1
                st["warn"] += onset - hit.min()
            st["hourly"] += min(1.0, (end - onset + 1) / 60)
    for sid, seg in enumerate(segments):
        if seg.patient in pset:
            stats[seg.patient]["hours"] += (len(seg) - meta[sid]) / 60
    return stats


def summarize(stats, patients):
    n = sum(stats[p]["n_events"] for p in patients)
    return dict(events=n,
                warn=sum(stats[p]["warn"] for p in patients) / max(n, 1),
                detected=sum(stats[p]["detected"] for p in patients) / max(n, 1),
                rate=sum(stats[p]["alerts"] for p in patients) / max(sum(stats[p]["hours"] for p in patients), 1e-9),
                hourly_detected=sum(stats[p]["hourly"] for p in patients) / max(n, 1))


def bootstrap(stats, patients, rng):
    pats = np.array(patients)
    out = []
    for _ in range(N_BOOT):
        out.append(summarize(stats, rng.choice(pats, len(pats))))
    return {k: (float(np.percentile([o[k] for o in out], 2.5)), float(np.percentile([o[k] for o in out], 97.5)))
            for k in ("warn", "detected", "rate")}


def average_precision(y, s):
    order = np.argsort(-s, kind="stable")
    y = np.asarray(y)[order]
    tp = np.cumsum(y)
    prec = tp / np.arange(1, len(y) + 1)
    return float((prec * y).sum() / max(y.sum(), 1))


def match_cutoff(df, scores, target_rate, events, meta, segments, patients, budget_hours):
    """Smallest cutoff whose training alert rate is <= target_rate (bisection over score quantiles)."""
    cand = np.unique(np.quantile(scores[np.isfinite(scores)], np.linspace(0.5, 0.99995, 400)))
    lo, hi = 0, len(cand) - 1
    pset = set(patients)
    sub = df[df.patient.isin(pset)]

    def rate(c):
        n = 0
        for sid, g in sub.groupby("seg_id"):
            n += len(alert_times(g.i.to_numpy(), scores[g.index] >= c))
        return n / budget_hours
    while lo < hi:
        mid = (lo + hi) // 2
        if rate(cand[mid]) <= target_rate:
            hi = mid
        else:
            lo = mid + 1
    return float(cand[lo])


# ---------- reports ----------
def report(segments, counts, df, events, meta):
    print("== cleaning counts ==")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print("== source-rate check (kept minutes) ==")
    for rate in ("1s", "1min"):
        ss = [s for s in segments if s.rate == rate]
        if not ss:
            continue
        line = [f"{rate}: {len(ss)} segments, {sum(len(s) for s in ss)} minutes"]
        for v in VITALS:
            x = np.concatenate([getattr(s, v) for s in ss])
            x = x[np.isfinite(x)]
            line.append(f"{v} p10/50/90 = {np.percentile(x, 10):.0f}/{np.median(x):.0f}/{np.percentile(x, 90):.0f}")
        hours = sum(len(s) - meta[i] for i, s in enumerate(segments) if s.rate == rate) / 60
        ev = sum(len(events[i]) for i, s in enumerate(segments) if s.rate == rate)
        line.append(f"events/100 h = {100 * ev / max(hours, 1e-9):.1f}")
        print("  " + "; ".join(line))
    v = df[df.valid]
    print("== labels ==")
    print(f"  patients {df.patient.nunique()}, live rows {len(df)}, valid rows {len(v)}, positives {int(v.label.sum())} "
          f"({100 * v.label.mean():.2f}%), fresh events {sum(len(e) for e in events.values())}")
    for vit in VITALS:
        col = v[f"pos_{vit}"]
        print(f"  positives {vit}: {int(col.sum())} rows, from {v[col == 1].patient.nunique()} patients")
    ev_by_vital = {vit: sum(1 for e in events.values() for x in e if vit in x[2]) for vit in VITALS}
    print(f"  fresh events by vital: {ev_by_vital}")


def show_positives(segments, df, n=20, seed=SEED):
    pos = df[df.valid & (df.label == 1)]
    pick = pos.sample(min(n, len(pos)), random_state=seed)
    print(f"== {len(pick)} random positive examples: 6 minutes up to row i, then 'i' then 21 minutes after (danger in []) ==")
    for _, r in pick.iterrows():
        seg = segments[int(r.seg_id)]
        i = int(r.i)
        vs = [v for v in VITALS if r[f"pos_{v}"]]
        v = vs[0]
        x = getattr(seg, v)
        fmt = lambda a: " ".join("." if not math.isfinite(y) else f"{y:.0f}" for y in a)
        print(f"{seg.patient} {seg.record[-16:]} {seg.rate} row {i} vitals {vs}\n   {v}: {fmt(x[max(0, i - 6):i])} | {x[i]:.0f} | {fmt(x[i + 1:i + 22])}")


# ---------- training ----------
def patient_split(patients, rng):
    pats = np.array(sorted(patients))
    rng.shuffle(pats)
    k = int(round(len(pats) * HELD_OUT_FRAC))
    return sorted(pats[k:]), sorted(pats[:k])


def group_folds(patients, rng):
    pats = np.array(patients)
    rng.shuffle(pats)
    return [list(pats[i::N_FOLDS]) for i in range(N_FOLDS)]


def lgb_params(spw):
    return dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=100, feature_fraction=0.8,
                bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, scale_pos_weight=spw, metric="average_precision",
                verbose=-1, seed=SEED, num_threads=4)


def weights_for(d):
    n = d.groupby("patient").patient.transform("size")
    w = 1.0 / n
    return (w / w.mean()).to_numpy()


def train_and_eval(segments, df, events, meta, ns):
    try:
        import lightgbm as lgb
    except Exception as e:  # missing libomp raises OSError
        lgb = None
        print(f"!! LightGBM unavailable ({e}); evaluating baselines only")
    rng = np.random.default_rng(SEED)
    patients = sorted(df.patient.unique())
    train_p, test_p = patient_split(patients, rng)
    feats = ff.FEATURE_NAMES
    df = df.reset_index(drop=True)
    df["distance"] = [ff.distance_score(r) for r in df[feats].to_dict("records")]
    df["extrap"] = [ff.extrapolation_score(r) for r in df[feats].to_dict("records")]
    tr_mask = df.patient.isin(train_p)
    valid = df.valid
    print(f"patients: {len(train_p)} train / {len(test_p)} held out; labeled rows train {int((tr_mask & valid).sum())} "
          f"(positives {int(df[tr_mask & valid].label.sum())}), test {int((~tr_mask & valid).sum())} "
          f"(positives {int(df[~tr_mask & valid].label.sum())})")

    def hours(ps):
        return sum((len(s) - meta[i]) for i, s in enumerate(segments) if s.patient in set(ps)) / 60

    budget = {}
    for name, ps in (("train", train_p), ("test", test_p)):
        pset = set(ps)
        n = sum(news2_alerts(ns[i], meta[i]) for i, s in enumerate(segments) if s.patient in pset)
        budget[name] = n / hours(ps)
    print(f"partial-NEWS2>=5 alert rate per patient-hour: train {budget['train']:.3f}, test {budget['test']:.3f}")
    target = budget["train"]

    scores = {"distance": df.distance.to_numpy(), "extrapolation": df.extrap.to_numpy()}
    results = {}
    best_iter = None
    if lgb is not None:
        oof = np.full(len(df), np.nan)
        folds = group_folds(train_p, rng)
        iters = []
        for k, val_p in enumerate(folds):
            vm = df.patient.isin(val_p)
            trn = df[tr_mask & ~vm & valid]
            val = df[vm & valid]
            spw = float(((1 - trn.label) * weights_for(trn)).sum() / max((trn.label * weights_for(trn)).sum(), 1e-9))
            m = lgb.train(lgb_params(spw), lgb.Dataset(trn[feats], trn.label, weight=weights_for(trn)),
                          num_boost_round=600, valid_sets=[lgb.Dataset(val[feats], val.label, weight=weights_for(val))],
                          callbacks=[lgb.early_stopping(50, verbose=False)])
            iters.append(m.best_iteration)
            oof[vm.to_numpy()] = m.predict(df.loc[vm, feats], num_iteration=m.best_iteration)
            print(f"  fold {k}: best_iter {m.best_iteration}, val AUPRC {average_precision(val.label, m.predict(val[feats], num_iteration=m.best_iteration)):.4f}")
        best_iter = int(np.median(iters))
        trn = df[tr_mask & valid]
        spw = float(((1 - trn.label) * weights_for(trn)).sum() / (trn.label * weights_for(trn)).sum())
        final = lgb.train(lgb_params(spw), lgb.Dataset(trn[feats], trn.label, weight=weights_for(trn)),
                          num_boost_round=best_iter)
        sc = np.full(len(df), np.nan)
        sc[(~tr_mask).to_numpy()] = final.predict(df.loc[~tr_mask, feats])
        sc[tr_mask.to_numpy()] = oof[tr_mask.to_numpy()]            # training rows: out-of-fold scores
        scores["lightgbm"] = sc

    ev_all = {}
    for name, s in scores.items():
        c = match_cutoff(df, s, target, events, meta, segments, train_p, hours(train_p))
        st_tr = per_patient_stats(df, s, c, events, meta, segments, train_p)
        st_te = per_patient_stats(df, s, c, events, meta, segments, test_p)
        te = df[~tr_mask & valid]
        results[name] = dict(cutoff=c, train=summarize(st_tr, train_p), test=summarize(st_te, test_p),
                             ci=bootstrap(st_te, test_p, np.random.default_rng(SEED)),
                             auprc_test=average_precision(te.label, s[te.index]),
                             auprc_train=average_precision(df[tr_mask & valid].label, s[df[tr_mask & valid].index]))
        ev_all[name] = st_te
    base = {k: results[k] for k in ("distance", "extrapolation")}
    better = max(base, key=lambda k: (results[k]["train"]["warn"], results[k]["train"]["detected"]))
    ship = better
    if "lightgbm" in results:
        L, B = results["lightgbm"], results[better]
        wins = all(L["test"][m] > B["test"][m] and L["ci"][m][0] > B["ci"][m][1] for m in ("warn", "detected"))
        ship = "lightgbm" if wins else better
        # paired bootstrap of the difference, informational only
        rng2, diffs = np.random.default_rng(SEED + 1), {"warn": [], "detected": []}
        for _ in range(N_BOOT):
            samp = rng2.choice(np.array(test_p), len(test_p))
            a, b = summarize(ev_all["lightgbm"], samp), summarize(ev_all[better], samp)
            for m in diffs:
                diffs[m].append(a[m] - b[m])
        results["paired_diff_ci"] = {m: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
                                     for m, v in diffs.items()}
    print("\n== held-out results (cutoffs matched to partial-NEWS2>=5 rate on training patients) ==")
    hdr = f"{'method':14s} {'cutoff':>9s} {'rate/h':>8s} {'warn min':>9s} {'warn 95% CI':>16s} {'detected':>9s} {'det 95% CI':>14s} {'AUPRC':>7s}"
    print(hdr)
    for name in ("lightgbm", "distance", "extrapolation"):
        if name not in results:
            continue
        r = results[name]
        print(f"{name:14s} {r['cutoff']:9.3f} {r['test']['rate']:8.3f} {r['test']['warn']:9.2f} "
              f"[{r['ci']['warn'][0]:.1f},{r['ci']['warn'][1]:.1f}]".ljust(56)
              + f" {r['test']['detected']:8.3f} [{r['ci']['detected'][0]:.2f},{r['ci']['detected'][1]:.2f}] {r['auprc_test']:7.4f}")
    t = results[better]["test"]
    print(f"{'hourly recheck':14s} {'-':>9s} {1.0:8.3f} {0.0:9.2f} {'':16s} {t['hourly_detected']:9.3f}   (1 check/h, random phase; detection only after onset)")
    print(f"held-out events {t['events']}, held-out NEWS2>=5 rate {budget['test']:.3f}/h; better baseline on training = {better}")
    if "paired_diff_ci" in results:
        print("paired bootstrap (lightgbm - better baseline), informational:", results["paired_diff_ci"])
    print("\n== informational: same methods at stricter alert budgets (not used for the ship rule) ==")
    extra = {}
    for tr in (0.25, 0.5):
        for name, s in scores.items():
            c = match_cutoff(df, s, tr, events, meta, segments, train_p, hours(train_p))
            r = summarize(per_patient_stats(df, s, c, events, meta, segments, test_p), test_p)
            extra[f"{name}@{tr}"] = r
            print(f"  target {tr}/h  {name:14s} rate {r['rate']:.3f}/h  warn {r['warn']:.1f} min  detected {r['detected']:.3f}")
    results["extra_budgets"] = extra
    print(f"SHIPS: {ship}")
    out = dict(ship=ship, better_baseline=better, target_rate_per_hour=target, budget=budget, results=results,
               best_iter=best_iter, n_train_patients=len(train_p), n_test_patients=len(test_p))
    PROC.mkdir(parents=True, exist_ok=True)
    (PROC / "fast_results.json").write_text(json.dumps(out, indent=2, default=float))
    if ship == "lightgbm":
        MODELS.mkdir(exist_ok=True)
        final.save_model(str(MODELS / "fast_15.txt"))
        (MODELS / "fast_15_features.json").write_text(json.dumps(
            dict(features=feats, cutoff=results["lightgbm"]["cutoff"], horizon_minutes=HORIZON), indent=2) + "\n")
        print("wrote models/fast_15.txt and models/fast_15_features.json")
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["report", "train"])
    ap.add_argument("--rebuild", action="store_true", help="ignore cached segments and rows")
    a = ap.parse_args()
    if a.rebuild:
        for f in (PROC / "mimic_segments.pkl", PROC / "fast_rows.pkl"):
            f.unlink(missing_ok=True)
    segments, counts = load_segments()
    df, events, meta, ns = build(segments)
    if a.stage == "report":
        report(segments, counts, df, events, meta)
        show_positives(segments, df)
    else:
        report(segments, counts, df, events, meta)
        train_and_eval(segments, df, events, meta, ns)


if __name__ == "__main__":
    sys.exit(main())
