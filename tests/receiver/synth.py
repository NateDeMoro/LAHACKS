"""Test-only RR generator with breathing (RSA) modulation, plus a 1-second batch feeder."""
import numpy as np


def make_beats(duration_s, br_bpm, hr=70, amp=40, jitter=15, drift=8, n_ectopic=3, n_skipped=0, seed=0):
    """Return (beat_times_s, rr_ms). br_bpm is a number or a function of time in seconds."""
    br_fn = br_bpm if callable(br_bpm) else (lambda t: br_bpm)
    rng = np.random.default_rng(seed)
    phase = rng.uniform(0, 2 * np.pi)
    drift_phase = rng.uniform(0, 2 * np.pi)
    t, rr = 0.0, []
    while t < duration_s:
        mean_hr = hr + drift * np.sin(2 * np.pi * t / 120 + drift_phase)
        r = max(60000 / mean_hr + amp * np.sin(phase) + rng.normal(0, jitter), 300)
        t += r / 1000
        phase += 2 * np.pi * br_fn(t) / 60 * r / 1000
        rr.append(r)
    rr = np.array(rr)
    for i in rng.choice(np.arange(5, len(rr) - 5), n_ectopic, replace=False):
        rr[i] *= 0.65
        rr[i + 1] *= 1.35
    rr = list(rr)
    # A missed detection shows up as one beat with the sum of two intervals.
    for i in sorted(rng.choice(np.arange(5, len(rr) - 5), n_skipped, replace=False), reverse=True):
        rr[i : i + 2] = [rr[i] + rr[i + 1]]
    rr = np.array(rr)
    return np.cumsum(rr) / 1000, rr


def drop_beats(times, rr, start_s, end_s):
    keep = (times < start_s) | (times >= end_s)
    return times[keep], rr[keep]


def feed(estimator, times, rr, start_s, end_s, step_s=1.0):
    """Feed beats in step_s batches like the strap; return [(now, estimate)] for each step."""
    out = []
    now = start_s
    while now < end_s:
        m = (times > now) & (times <= now + step_s)
        estimator.add_beats(times[m].tolist(), rr[m].tolist())
        now += step_s
        out.append((now, estimator.estimate(now)))
    return out
