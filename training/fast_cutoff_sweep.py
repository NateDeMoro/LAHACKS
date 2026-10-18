"""Exploration: Rule 2 (extrapolation) across cutoffs on the 52 held-out MIMIC patients, with false-alert rates and
Rule 1 rows at matched alert budgets. Use when choosing or defending a trend warning cutoff. No ship decision.
A false alert = an alert not followed by an event onset (5+ consecutive observed minutes in danger) within 20 minutes."""
import numpy as np

from backend.risk_engine import fast_features as ff
from training import train_fast as tf
from training.fast_labels import label_segment
from training.mimic_numerics import load_segments

CUTS = (0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.258)
FALSE_WINDOW = 20


def main():
    segments, _ = load_segments()
    df, events, meta, ns = tf.build(segments)
    df = df.reset_index(drop=True)
    rng = np.random.default_rng(tf.SEED)
    train_p, test_p = tf.patient_split(sorted(df.patient.unique()), rng)
    te = df[df.patient.isin(set(test_p))]
    feats = te[ff.FEATURE_NAMES].to_dict("records")
    sc = {"extrapolation": np.array([ff.extrapolation_score(r) for r in feats]),
          "distance": np.array([ff.distance_score(r) for r in feats])}
    te = te.reset_index(drop=True)
    onsets = {sid: np.array(sorted(a for v in lab.event_runs.values() for a, _ in v))
              for sid, lab in ((s, label_segment(segments[s])) for s in te.seg_id.unique())}
    hours = sum((len(s) - meta[i]) for i, s in enumerate(segments) if s.patient in set(test_p)) / 60

    def evaluate(method, cutoff):
        s = sc[method]
        alerts = false = 0
        per_patient = {p: dict(n_events=0, warn=0.0, detected=0, hours=0.0, alerts=0, hourly=0.0) for p in test_p}
        alerts_by_seg = {}
        for sid, g in te.groupby("seg_id"):
            al = np.array(tf.alert_times(g.i.to_numpy(), s[g.index] >= cutoff), int)
            alerts_by_seg[sid] = al
            on = onsets[sid]
            for a in al:
                alerts += 1
                if not ((on > a) & (on <= a + FALSE_WINDOW)).any():
                    false += 1
        # reuse the standard metric code on a score column aligned to the full df
        full = np.full(len(df), np.nan)
        full[df.index[df.patient.isin(set(test_p))]] = s
        st = tf.per_patient_stats(df, full, cutoff, events, meta, segments, test_p)
        sm = tf.summarize(st, test_p)
        ci = tf.bootstrap(st, test_p, np.random.default_rng(tf.SEED))
        return dict(cut=cutoff, rate=alerts / hours, false_rate=false / hours, false_share=false / max(alerts, 1),
                    warn=sm["warn"], warn_ci=ci["warn"], detected=sm["detected"], det_ci=ci["detected"])

    def row(method, r):
        print(f"{method:13s} {r['cut']:7.3f} {r['rate']:7.3f} {r['false_rate']:7.3f} {100 * r['false_share']:6.1f}% "
              f"{r['warn']:6.1f} [{r['warn_ci'][0]:.1f},{r['warn_ci'][1]:.1f}] {r['detected']:6.3f} [{r['det_ci'][0]:.2f},{r['det_ci'][1]:.2f}]")

    print(f"held-out patients {len(test_p)}, {hours:.0f} monitored hours")
    print(f"{'method':13s} {'cutoff':>7s} {'alerts/h':>7s} {'false/h':>7s} {'false%':>7s} {'warn min (95% CI)':>18s} {'caught (95% CI)':>16s}")
    r2 = [evaluate("extrapolation", c) for c in CUTS]
    for r in r2:
        row("extrapolation", r)
    cand = np.round(np.arange(-3.0, 1.5, 0.02), 2)
    rates = {c: evaluate("distance", c)["rate"] for c in cand[::5]}
    for target in (r2[0], r2[2], r2[4]):
        best = min(cand[::5], key=lambda c: abs(rates[c] - target["rate"]))
        fine = [c for c in cand if abs(c - best) <= 0.1]
        best = min(fine, key=lambda c: abs(evaluate("distance", c)["rate"] - target["rate"]))
        row("distance", evaluate("distance", best))


if __name__ == "__main__":
    main()
