"""T6 "Option 1": forecast each vital's lowest/highest value in the next 15 minutes with LightGBM, alert when the
cautious forecast lands past the danger edge. Use when reproducing the forecast numbers, regenerating
models/fast_15_forecast*, or re-running the evaluation on a different directory of records.

  python -m training.fast_forecast train                      # CV search, fit, held-out evaluation, writes models/
  python -m training.fast_forecast train --records-dir A B    # same, pooling several records dirs (own caches)
  python -m training.fast_forecast eval --records-dir DIR     # saved models on every patient found under DIR
  python -m training.fast_forecast bench                      # per-minute inference time, model sizes, load time
  python -m training.fast_forecast demo                       # SpO2 drop fixture at several cutoffs

Targets per row (minute i, from the segment's 15th observed minute, not in danger): lowest SpO2, lowest and highest
breathing, lowest and highest HR over minutes i+1..i+15. A target is skipped when the full 15-minute window is not
inside the segment or fewer than MIN_OBS (12 = 75%, the old 15-of-20 rule) of its minutes are observed. Models predict
(target - current 5-minute median); a median model and a cautious quantile model (0.1 low / 0.9 high) per target.
Score = edge - cautious forecast (low) or cautious forecast - edge (high), max over targets: Rule 2's units.
"""
import argparse
import contextlib
import io
import json
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from backend.risk_engine import fast_features as ff
from training import train_fast as tf
from training.fast_labels import HORIZON, label_segment
from training.mimic_numerics import RAW, load_segments

MODELS = tf.MODELS
BUNDLE = MODELS / "fast_15_forecast.json"
MIN_OBS = 12
STRIDE = 3                      # fit on every 3rd minute: neighbours are near-duplicates, 3x faster
TARGETS = [("spo2_low", "spo2", "low", 0.1), ("rr_low", "resp_rate", "low", 0.1), ("rr_high", "resp_rate", "high", 0.9),
           ("hr_low", "hr", "low", 0.1), ("hr_high", "hr", "high", 0.9)]
GRID = [(7, 200), (7, 800), (15, 200), (15, 800)]   # (num_leaves, min_data_in_leaf)
CUTS = (0, 0.5, 1.0, 1.5, 2.0)
FALSE_WINDOW = 20
ARR = {"hr": "hr", "resp_rate": "resp_rate", "spo2": "spo2"}


# ---------- targets ----------
def window_extreme(x: np.ndarray, kind: str, horizon: int = HORIZON, min_obs: int = MIN_OBS) -> np.ndarray:
    """Per minute i: min ("low") or max ("high") of the observed values in minutes i+1..i+horizon; NaN when the
    full window does not fit in the array or fewer than min_obs of its minutes are observed. Use for forecast targets."""
    n = len(x)
    out = np.full(n, np.nan)
    if n <= horizon:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x[1:], horizon)[: n - horizon]   # window k = x[k+1 : k+1+horizon]
    ok = np.isfinite(win).sum(axis=1) >= min_obs
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN windows are dropped by `ok`
        ext = np.nanmin(win, axis=1) if kind == "low" else np.nanmax(win, axis=1)
    out[: n - horizon] = np.where(ok, ext, np.nan)
    return out


def build_targets(seg) -> dict:
    return {name: window_extreme(getattr(seg, vital), kind) for name, vital, kind, _ in TARGETS}


def add_targets(df: pd.DataFrame, segments) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    for name, *_ in TARGETS:
        df["y_" + name] = np.nan
    for sid, g in df.groupby("seg_id"):
        tg = build_targets(segments[sid])
        for name, *_ in TARGETS:
            df.loc[g.index, "y_" + name] = tg[name][g.i.to_numpy()]
    return df


def current(df, vital):
    return df[f"{vital}_5_med"].to_numpy(float)


def edge_of(vital, kind):
    return ff.LOW_EDGE[vital] if kind == "low" else ff.HIGH_EDGE[vital]


def score_from(cau: dict) -> np.ndarray:
    """Alert score per row from cautious forecasts {target: forecast}: max over targets of distance past the edge."""
    cols = []
    for name, vital, kind, _ in TARGETS:
        fc = cau[name]
        cols.append(edge_of(vital, kind) - fc if kind == "low" else fc - edge_of(vital, kind))
    m = np.vstack(cols)
    with np.errstate(all="ignore"):
        s = np.nanmax(np.where(np.isfinite(m), m, -np.inf), axis=0)
    return np.where(np.isfinite(s), s, -1e9)


# ---------- fitting ----------
def params(alpha, leaves, min_leaf):
    return dict(objective="quantile", alpha=alpha, metric="quantile", learning_rate=0.08, num_leaves=leaves,
                min_data_in_leaf=min_leaf, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0,
                verbose=-1, seed=tf.SEED, num_threads=8)


def cv_fit(lgb, d, y, folds, p, all_rows=None, all_y_off=None):
    """Patient-grouped CV on strided rows d (target y). Returns (mean best validation pinball, best iterations,
    out-of-fold predictions for all_rows if given)."""
    losses, iters = [], []
    oof = np.full(len(all_rows), np.nan) if all_rows is not None else None
    for val_p in folds:
        vm = d.patient.isin(val_p).to_numpy()
        trn, val = d[~vm], d[vm]
        m = lgb.train(p, lgb.Dataset(trn[ff.FEATURE_NAMES], y[~vm], weight=tf.weights_for(trn)), num_boost_round=500,
                      valid_sets=[lgb.Dataset(val[ff.FEATURE_NAMES], y[vm], weight=tf.weights_for(val))],
                      callbacks=[lgb.early_stopping(30, verbose=False)])
        losses.append(m.best_score["valid_0"]["quantile"])
        iters.append(m.best_iteration)
        if oof is not None:
            vmask = all_rows.patient.isin(val_p).to_numpy()
            oof[vmask] = m.predict(all_rows.loc[vmask, ff.FEATURE_NAMES], num_iteration=m.best_iteration)
    return float(np.mean(losses)), iters, oof


def fit_all(df, train_p, tr_mask):
    import lightgbm as lgb
    rng = np.random.default_rng(tf.SEED)
    folds = tf.group_folds(train_p, rng)
    models, info, oof_cau = {}, {}, {}
    for name, vital, kind, alpha in TARGETS:
        cur = current(df, vital)
        usable = tr_mask.to_numpy() & np.isfinite(df["y_" + name].to_numpy()) & np.isfinite(cur)
        rows = df[usable]
        d = rows.iloc[::STRIDE]
        y = (df["y_" + name].to_numpy() - cur)[usable]
        yd = y[::STRIDE]
        best = None
        for leaves, min_leaf in GRID:
            loss, its, _ = cv_fit(lgb, d, yd, folds, params(0.5, leaves, min_leaf))
            print(f"  {name} median leaves {leaves} min_leaf {min_leaf}: CV pinball {loss:.4f}, iters {its}", flush=True)
            if best is None or loss < best[0]:
                best = (loss, leaves, min_leaf, its)
        _, leaves, min_leaf, its_med = best
        loss_c, its_c, oof = cv_fit(lgb, d, yd, folds, params(alpha, leaves, min_leaf), all_rows=rows)
        full = np.full(len(df), np.nan)
        full[np.nonzero(usable)[0]] = oof
        oof_cau[name] = current(df, vital) + full
        rounds = {"median": int(np.median(its_med) * 1.1) + 1, "cautious": int(np.median(its_c) * 1.1) + 1}
        w = tf.weights_for(d)
        for tag, a in (("median", 0.5), ("cautious", alpha)):
            models[(name, tag)] = lgb.train(params(a, leaves, min_leaf), lgb.Dataset(d[ff.FEATURE_NAMES], yd, weight=w),
                                            num_boost_round=rounds[tag])
        info[name] = dict(num_leaves=leaves, min_data_in_leaf=min_leaf, rounds=rounds, cv_pinball_median=best[0],
                          cv_pinball_cautious=loss_c, fit_rows=len(d))
        print(f"  {name}: chose leaves {leaves} min_leaf {min_leaf}, rounds {rounds}", flush=True)
    return models, info, oof_cau


def predict_frame(boosters: dict, df):
    """boosters {(target, "median"/"cautious"): Booster}. Returns (median forecasts, cautious forecasts) as
    {target: array} in raw units (current 5-minute median + predicted change); NaN where the vital has no 5-min median."""
    X = df[ff.FEATURE_NAMES].to_numpy(float)
    med, cau = {}, {}
    for name, vital, kind, _ in TARGETS:
        cur = current(df, vital)
        med[name] = cur + boosters[(name, "median")].predict(X, num_threads=8)
        cau[name] = cur + boosters[(name, "cautious")].predict(X, num_threads=8)
    return med, cau


def load_boosters():
    import lightgbm as lgb
    meta = json.loads(BUNDLE.read_text())
    return {(t["name"], tag): lgb.Booster(model_file=str(MODELS / t[f"{tag}_file"])) for t in meta["targets"]
            for tag in ("median", "cautious")}, meta


# ---------- evaluation ----------
def forecast_table(df, rows_mask, med, cau):
    """MAE of the median forecast vs no-change and Rule 2's straight line, and quantile coverage, per target.
    Common rows: target known and both the 5-min median and the 15-min slope available."""
    out = []
    for name, vital, kind, alpha in TARGETS:
        y, cur = df["y_" + name].to_numpy(), current(df, vital)
        slope = df[f"{vital}_15_slope"].to_numpy(float)
        ok = rows_mask & np.isfinite(y) & np.isfinite(cur) & np.isfinite(slope)
        line = cur + 15 * slope
        rule2 = np.minimum(cur, line) if kind == "low" else np.maximum(cur, line)   # extreme of start and endpoint
        beyond = (y < cau[name]) if kind == "low" else (y > cau[name])
        out.append(dict(target=name, n=int(ok.sum()), mae_forecast=float(np.abs(y - med[name])[ok].mean()),
                        mae_nochange=float(np.abs(y - cur)[ok].mean()), mae_rule2=float(np.abs(y - rule2)[ok].mean()),
                        mae_rule2_endpoint=float(np.abs(y - line)[ok].mean()),
                        coverage_beyond=float(beyond[ok].mean()), nominal=alpha if kind == "low" else 1 - alpha))
    return out


class AlertEval:
    """Alert table machinery for a set of patients: score columns are aligned to df's index."""

    def __init__(self, df, segments, events, meta, patients):
        self.df, self.segments, self.events, self.meta, self.patients = df, segments, events, meta, list(patients)
        pset = set(patients)
        self.sub = df[df.patient.isin(pset)]
        self.groups = [(sid, g.index.to_numpy(), g.i.to_numpy()) for sid, g in self.sub.groupby("seg_id")]
        self.onsets = {sid: np.array(sorted(a for v in label_segment(segments[sid]).event_runs.values() for a, _ in v))
                       for sid, _, _ in self.groups}
        self.hours = sum(len(s) - meta[i] for i, s in enumerate(segments) if s.patient in pset) / 60

    def rate(self, score, cutoff):
        return sum(len(tf.alert_times(i, score[idx] >= cutoff)) for _, idx, i in self.groups) / self.hours

    def run(self, score, cutoff):
        alerts = false = 0
        for sid, idx, i in self.groups:
            on = self.onsets[sid]
            for a in tf.alert_times(i, score[idx] >= cutoff):
                alerts += 1
                false += not ((on > a) & (on <= a + FALSE_WINDOW)).any()
        st = tf.per_patient_stats(self.df, score, cutoff, self.events, self.meta, self.segments, self.patients)
        sm = tf.summarize(st, self.patients)
        ci = tf.bootstrap(st, self.patients, np.random.default_rng(tf.SEED))
        return dict(cut=float(cutoff), rate=alerts / self.hours, false_rate=false / self.hours,
                    false_share=false / max(alerts, 1), warn=sm["warn"], warn_ci=ci["warn"],
                    detected=sm["detected"], det_ci=ci["detected"], events=sm["events"],
                    cwarn=sm["cwarn"], cwarn_ci=ci["cwarn"], cdetected=sm["cdetected"], cdet_ci=ci["cdetected"])

    def match(self, score, target_rate):
        """Cutoff whose held-out alert rate is closest to target_rate (coarse then fine search)."""
        coarse = np.arange(-6, 14, 0.25)
        best = min(coarse, key=lambda c: abs(self.rate(score, c) - target_rate))
        fine = np.arange(best - 0.25, best + 0.2501, 0.01)
        return float(min(fine, key=lambda c: abs(self.rate(score, c) - target_rate)))


def print_forecast_table(rows):
    print(f"{'target':9s} {'rows':>8s} {'MAE forecast':>13s} {'no change':>10s} {'Rule 2 line':>12s} {'(endpoint)':>11s} "
          f"{'beyond cautious':>16s} {'nominal':>8s}")
    for r in rows:
        print(f"{r['target']:9s} {r['n']:8d} {r['mae_forecast']:13.3f} {r['mae_nochange']:10.3f} {r['mae_rule2']:12.3f} "
              f"{r['mae_rule2_endpoint']:11.3f} {100 * r['coverage_beyond']:15.1f}% {100 * r['nominal']:7.0f}%")


def print_alert_header():
    print(f"{'method':14s} {'cutoff':>7s} {'alerts/h':>8s} {'false/h':>7s} {'false%':>7s} {'warn min (95% CI)':>20s} "
          f"{'caught (95% CI)':>17s} {'CAPPED warn (CI)':>20s} {'CAPPED caught (CI)':>20s}")


def print_alert_row(method, r):
    print(f"{method:14s} {r['cut']:7.3f} {r['rate']:8.3f} {r['false_rate']:7.3f} {100 * r['false_share']:6.1f}% "
          f"{r['warn']:6.1f} [{r['warn_ci'][0]:.1f},{r['warn_ci'][1]:.1f}] {r['detected']:7.3f} "
          f"[{r['det_ci'][0]:.2f},{r['det_ci'][1]:.2f}] "
          f"{r['cwarn']:6.1f} [{r['cwarn_ci'][0]:.1f},{r['cwarn_ci'][1]:.1f}] {r['cdetected']:7.3f} "
          f"[{r['cdet_ci'][0]:.2f},{r['cdet_ci'][1]:.2f}]")


def alert_report(ev: AlertEval, score_fc, score_r2, matched_cut):
    print(f"patients {len(ev.patients)}, {ev.hours:.0f} monitored hours, {rows_events(ev)} events")
    print_alert_header()
    results = []
    for c in (*CUTS, matched_cut):
        r = ev.run(score_fc, c)
        r["label"] = f"forecast {'(NEWS2-matched)' if c == matched_cut else ''}".strip()
        results.append(r)
        print_alert_row("forecast", r)
        c2 = ev.match(score_r2, r["rate"])
        r2 = ev.run(score_r2, c2)
        r2["label"] = "rule2"
        results.append(r2)
        print_alert_row("  rule2 same /h", r2)
    return results


def rows_events(ev):
    return sum(len(ev.events[s]) for s, _, _ in ev.groups)


def rows_for(segments):
    """Feature rows, events and first-row index for segments, without any cache (use for a new records dir)."""
    rows, events, meta = [], {}, {}
    with ProcessPoolExecutor() as ex:
        for sid, recs, evs, first_row, _ in ex.map(tf.segment_rows, list(enumerate(segments)), chunksize=4):
            rows += recs
            events[sid], meta[sid] = evs, first_row
    df = pd.DataFrame(rows)
    df["patient"] = [segments[s].patient for s in df.seg_id]
    return df, events, meta


# ---------- stages ----------
def stage_train(records_dirs=None):
    if records_dirs:   # pooled dirs get their own caches so batch-1-only pickles are never reused
        segments, counts = load_segments([Path(d) for d in records_dirs], cache=tf.PROC / "mimic_segments_pooled.pkl")
        print(f"pooled {len(records_dirs)} dirs: {counts['patients_seen']} patients with records, "
              f"{counts['patients_kept']} after filters, {len(segments)} segments")
        df, events, meta, ns = tf.build(segments, "fast_rows_pooled.pkl")
    else:
        segments, _ = load_segments()
        df, events, meta, ns = tf.build(segments)
    df = add_targets(df, segments)
    rng = np.random.default_rng(tf.SEED)
    train_p, test_p = tf.patient_split(sorted(df.patient.unique()), rng)   # identical split to earlier rounds
    tr_mask = df.patient.isin(train_p)
    print(f"patients {len(train_p)} train / {len(test_p)} held out; rows {len(df)}")
    models, info, oof_cau = fit_all(df, train_p, tr_mask)
    med, cau = predict_frame({k: v for k, v in models.items()}, df)
    # training rows use out-of-fold cautious forecasts for the cutoff match; held-out rows use the final models
    te = (~tr_mask).to_numpy()
    cau_mix = {n: np.where(te, cau[n], oof_cau[n]) for n in cau}
    score_fc = score_from(cau_mix)
    score_r2 = np.array([ff.extrapolation_score(r) for r in df[ff.FEATURE_NAMES].to_dict("records")])

    hours = lambda ps: sum(len(s) - meta[i] for i, s in enumerate(segments) if s.patient in set(ps)) / 60
    n2_rate = sum(tf.news2_alerts(ns[i], meta[i]) for i, s in enumerate(segments) if s.patient in set(train_p)) / hours(train_p)
    matched = tf.match_cutoff(df, score_fc, n2_rate, events, meta, segments, train_p, hours(train_p))
    print(f"partial-NEWS2>=5 alert rate on training patients {n2_rate:.3f}/h -> forecast cutoff {matched:.3f}")

    ev = AlertEval(df, segments, events, meta, test_p)
    print("\n== held-out forecast quality ==")
    ft = forecast_table(df, te, med, cau)
    print_forecast_table(ft)
    print("\n== training patients, out-of-fold coverage (cautious) ==")
    _, oof_only = med, oof_cau
    print_forecast_table(forecast_table(df, ~te, {n: np.full(len(df), np.nan) for n in med}, oof_cau))
    print("\n== held-out alerts: forecast score vs Rule 2 at the same alert rate ==")
    results = alert_report(ev, score_fc, score_r2, matched)

    MODELS.mkdir(exist_ok=True)
    targets = []
    for name, vital, kind, alpha in TARGETS:
        t = dict(name=name, vital=vital, kind=kind, alpha=alpha, **info[name])
        for tag in ("median", "cautious"):
            t[f"{tag}_file"] = f"fast_15_forecast_{name}_{tag}.txt"
            models[(name, tag)].save_model(str(MODELS / t[f"{tag}_file"]))
        targets.append(t)
    BUNDLE.write_text(json.dumps(dict(horizon_minutes=HORIZON, min_obs=MIN_OBS, features=ff.FEATURE_NAMES, targets=targets,
                                      cutoff=matched, news2_matched_rate_per_hour=n2_rate,
                                      note="models predict (target - current 5-min median); score = edge - cautious "
                                           "forecast (low) or cautious forecast - edge (high), max over targets"),
                                 indent=1) + "\n")
    tf.PROC.mkdir(parents=True, exist_ok=True)
    (tf.PROC / "fast_forecast_results.json").write_text(json.dumps(dict(forecast=ft, alerts=results, info=info,
                                                                        matched_cutoff=matched), indent=1, default=float))
    print("wrote", BUNDLE.name, "and", len(TARGETS) * 2, "model files")


def stage_eval(records_dir):
    boosters, meta = load_boosters()
    segments, counts = load_segments(Path(records_dir), use_cache=False)
    print(f"records dir {records_dir}: {len(segments)} segments, {len({s.patient for s in segments})} patients")
    df, events, fmeta = rows_for(segments)
    df = add_targets(df, segments)
    patients = sorted(df.patient.unique())
    med, cau = predict_frame(boosters, df)
    print("\n== forecast quality ==")
    print_forecast_table(forecast_table(df, np.ones(len(df), bool), med, cau))
    score_fc = score_from(cau)
    score_r2 = np.array([ff.extrapolation_score(r) for r in df[ff.FEATURE_NAMES].to_dict("records")])
    print("\n== alerts: forecast score vs Rule 2 at the same alert rate (matched cutoff from the training patients) ==")
    alert_report(AlertEval(df, segments, events, fmeta, patients), score_fc, score_r2, meta["cutoff"])


def stage_bench():
    from datetime import datetime, timedelta, timezone
    from backend.contracts import PeriodSummary
    from backend.risk_engine import fast_model
    from backend.risk_engine.trend import TrendHistory
    segments, _ = load_segments()
    seg = max(segments, key=lambda s: np.isfinite(s.spo2).sum() + np.isfinite(s.hr).sum())
    fast_model.METHOD = "forecast"
    t0 = time.perf_counter()
    assert fast_model.load()
    print(f"load (lazy: LightGBM import + 5 cautious models): {1000 * (time.perf_counter() - t0):.0f} ms")
    import lightgbm as lgb
    t0 = time.perf_counter()
    med = [lgb.Booster(model_file=str(MODELS / t["median_file"])) for t in fast_model._forecast["meta"]["targets"]]
    print(f"load 5 median models: {1000 * (time.perf_counter() - t0):.0f} ms")
    hist, t_pred, t_feat, t_all = TrendHistory(), [], [], []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n_pred = 0
    for k in range(len(seg)):
        hist.add(PeriodSummary(patient_id="p", period_ts=base + timedelta(minutes=k),
                               hr=None if np.isnan(seg.hr[k]) else float(seg.hr[k]),
                               resp_rate=None if np.isnan(seg.resp_rate[k]) else float(seg.resp_rate[k]),
                               spo2=None if np.isnan(seg.spo2[k]) else float(seg.spo2[k]), temp_c=36.8, clean_seconds=60))
        if k < 20:
            continue
        s = time.perf_counter()
        fast_model.predict(hist)
        t_pred.append(1000 * (time.perf_counter() - s))
        rows = list(hist.rows)
        tt = [(r.ts - rows[0].ts).total_seconds() / 60 for r in rows]
        s = time.perf_counter()
        f = ff.compute_features({v: (tt, [getattr(r, v) for r in rows]) for v in ff.VITALS}, tt[-1])
        t_feat.append(1000 * (time.perf_counter() - s))
        x = np.array([[f[n] for n in ff.FEATURE_NAMES]], float)
        s = time.perf_counter()
        for b in med:
            b.predict(x, num_threads=1)
        t_all.append(t_pred[-1] + 1000 * (time.perf_counter() - s))
        n_pred += 1
    for label, a in (("predict(): features + 5 cautious models", t_pred), ("features only", t_feat),
                     ("features + all 10 models (median too)", t_all)):
        print(f"{label}: median {np.median(a):.2f} ms, p99 {np.percentile(a, 99):.2f} ms over {len(a)} minutes")
    total = 0
    for f in sorted(MODELS.glob("fast_15_forecast*")):
        total += f.stat().st_size
        print(f"{f.name}: {f.stat().st_size / 1024:.0f} KB")
    print(f"total {total / 1024:.0f} KB")


def stage_demo(path):
    from backend.risk_engine import engine, fast_model
    from scripts import replay_fixture as rf
    fast_model.METHOD = "forecast"
    fast_model._forecast = None
    assert fast_model.load()
    base = engine.load_config()
    orig = engine.load_config
    f = rf.load_i6(Path(path))
    print("minute  SpO2  forecast(cautious SpO2 low)  score")
    eng = engine.RiskEngine(base)
    for k, m in enumerate(f, 1):
        res = eng.on_period(m)
        if 30 <= k <= 48:
            print(f"{k:5d}  {m.spo2:5.1f}  {res.trend_reason_fast}  {res.trend_prob_fast}")
    for c in (0, 0.5, 1.0, 1.5, 2.0, json.loads(BUNDLE.read_text())["cutoff"]):
        cfg = base.model_copy(deep=True)
        cfg.trend.fast_warning_cutoff = c
        eng = engine.RiskEngine(cfg)
        ap = rf.AlertPrinter(eng, None)
        first_warn, buf = None, io.StringIO()
        for k, m in enumerate(f, 1):
            with contextlib.redirect_stdout(buf):
                r = eng.on_period(m)
                ap.feed(r)
            if first_warn is None and r.trend_tier == "warning":
                first_warn = (k, m.spo2)
        alerts = [l.strip() for l in buf.getvalue().splitlines() if "ALERT" in l and "trend" in l.lower()]
        print(f"cutoff {c:.2f}: trend tier warning first at {first_warn}; trend alerts: {alerts or 'none'}")
        print("   all alert lines:", [l.strip() for l in buf.getvalue().splitlines() if "ALERT" in l] or "none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["train", "eval", "bench", "demo"])
    ap.add_argument("--records-dir", nargs="+", help="eval: directory of MIMIC-III wdb records (p*/p*/*.hea) to "
                    "evaluate on; train: one or more dirs to pool (default is the batch-1 cache)")
    ap.add_argument("--fixture", default="fixtures/fast_spo2_drop_i6.jsonl")
    a = ap.parse_args()
    if a.stage == "train":
        stage_train(a.records_dir)
    elif a.stage == "eval":
        stage_eval(a.records_dir[0] if a.records_dir else RAW)
    elif a.stage == "bench":
        stage_bench()
    else:
        stage_demo(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
