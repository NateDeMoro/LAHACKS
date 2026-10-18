"""Label and event definitions for the T6 fast trend model (15-minute horizon).
Use when building training rows, scoring alerts against events, or checking label edge cases.

Danger = NEWS2 score 3 per vital (HR <=40 or >=131, breathing <=8 or >=25, SpO2 <=91). An event is >= 5
consecutive observed minutes in danger for one vital (a null minute breaks the run); its onset is the run's first
minute. A row (minute i, not in danger, from the segment's 15th observed minute) is positive if some vital's event
onset falls in (i, i+15]. A negative row needs >= 15 observed minutes per vital in the next 20. Rows inside an event
or within 30 minutes after one are excluded.
"""
from dataclasses import dataclass, field

import numpy as np

from training.mimic_numerics import VITALS, Segment, in_danger

HORIZON = 15
MIN_RUN = 5
AFTER_EVENT = 30
NEG_LOOKAHEAD, NEG_MIN_OBS = 20, 15
START_OBSERVED = 15


def danger_runs(mask: np.ndarray, min_run: int = MIN_RUN):
    """(start, end) inclusive index pairs of runs of True at least min_run long. Use for events."""
    runs, n, i = [], len(mask), 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j - i + 1 >= min_run:
                runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


@dataclass
class Labeled:
    seg: Segment
    first_row: int                  # index of the 15th observed minute
    live_row: np.ndarray            # observed, not in danger, from first_row: where the live model would run
    valid: np.ndarray               # live_row and labelable (not excluded, enough look-ahead data for negatives)
    label: np.ndarray               # 1/0, meaningful where valid
    pos_by_vital: dict = field(default_factory=dict)
    events: list = field(default_factory=list)   # fresh events: (onset, end, vitals) with onset > first_row
    event_runs: dict = field(default_factory=dict)


def label_segment(seg: Segment) -> Labeled:
    n = len(seg)
    arrs = {"hr": seg.hr, "resp_rate": seg.resp_rate, "spo2": seg.spo2}
    dh, dr, ds = in_danger(seg.hr, seg.resp_rate, seg.spo2)
    danger = {"hr": dh, "resp_rate": dr, "spo2": ds}
    obs_v = {v: np.isfinite(a) for v, a in arrs.items()}
    obs = obs_v["hr"] | obs_v["resp_rate"] | obs_v["spo2"]
    obs_idx = np.nonzero(obs)[0]
    first_row = int(obs_idx[START_OBSERVED - 1]) if len(obs_idx) >= START_OBSERVED else n
    any_danger = dh | dr | ds
    live = obs & ~any_danger
    live[:first_row] = False

    runs = {v: danger_runs(danger[v]) for v in VITALS}
    excluded = np.zeros(n, bool)
    for v in VITALS:
        for a, z in runs[v]:
            excluded[a: min(n, z + AFTER_EVENT + 1)] = True

    pos_v = {}
    for v in VITALS:
        onset = np.zeros(n + 1, int)
        for a, _ in runs[v]:
            onset[a] = 1
        cs = np.concatenate([[0], np.cumsum(onset[:n])])      # cs[k] = onsets in [0, k)
        i = np.arange(n)
        hi = np.minimum(i + HORIZON + 1, n)
        pos_v[v] = (cs[hi] - cs[i + 1]) > 0                    # onsets in (i, i+15]
    label = pos_v["hr"] | pos_v["resp_rate"] | pos_v["spo2"]

    enough = np.ones(n, bool)
    for v in VITALS:
        c = np.concatenate([[0], np.cumsum(obs_v[v])])
        i = np.arange(n)
        hi = np.minimum(i + NEG_LOOKAHEAD + 1, n)
        enough &= (c[hi] - c[i + 1]) >= NEG_MIN_OBS
    valid = live & ~excluded & (label | enough)

    merged, last_end = [], -10**9
    allruns = sorted((a, z, v) for v in VITALS for a, z in runs[v])
    cur = None
    for a, z, v in allruns:
        if cur and a <= cur[1] + 1:
            cur = (cur[0], max(cur[1], z), cur[2] | {v})
        else:
            if cur:
                merged.append(cur)
            cur = (a, z, {v})
    if cur:
        merged.append(cur)
    events = []
    for a, z, vs in merged:
        if a > last_end + AFTER_EVENT and a > first_row:
            events.append((a, z, tuple(sorted(vs))))
        last_end = z
    return Labeled(seg, first_row, live, valid, label & valid, {v: pos_v[v] & valid for v in VITALS}, events, runs)
