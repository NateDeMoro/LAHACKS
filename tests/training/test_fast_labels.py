import numpy as np

from training.fast_labels import HORIZON, danger_runs, label_segment
from training.mimic_numerics import Segment


def seg(n=100, hr=None, rr=None, sp=None):
    return Segment("p", "r", "1min", 0, np.full(n, 75.0) if hr is None else np.asarray(hr, float),
                   np.full(n, 16.0) if rr is None else np.asarray(rr, float),
                   np.full(n, 97.0) if sp is None else np.asarray(sp, float), np.full(n, np.nan))


def sp_with_event(onset, length, n=100):
    sp = np.full(n, 97.0)
    sp[onset: onset + length] = 88.0
    return sp


def test_danger_runs_min_length_and_null_break():
    m = np.array([0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1], bool)
    assert danger_runs(m) == [(6, 10)]


def test_four_minute_event_does_not_count():
    lab = label_segment(seg(sp=sp_with_event(40, 4)))
    assert lab.label.sum() == 0 and lab.events == []


def test_null_minute_breaks_run():
    sp = sp_with_event(40, 8)
    sp[43] = np.nan
    lab = label_segment(seg(sp=sp))
    assert lab.label.sum() == 0                  # runs of 3 and 4 observed minutes


def test_onset_boundary_at_horizon():
    lab = label_segment(seg(sp=sp_with_event(40, 8)))
    i = 40 - HORIZON                             # onset exactly 15 minutes ahead
    assert lab.label[i] and not lab.label[i - 1] and lab.label[39] and not lab.label[40]
    assert lab.pos_by_vital["spo2"][i] and not lab.pos_by_vital["hr"][i]


def test_in_event_and_after_event_excluded():
    lab = label_segment(seg(n=140, sp=sp_with_event(40, 8, 140)))
    assert not lab.valid[40:48].any()            # inside the event
    end = 47
    assert not lab.valid[end + 1: end + 31].any() and lab.valid[end + 31]


def test_first_row_is_15th_observed_minute():
    lab = label_segment(seg())
    assert lab.first_row == 14 and not lab.live_row[13] and lab.live_row[14]


def test_negative_needs_enough_lookahead_data():
    rr = np.full(100, 16.0)
    rr[30:60] = np.nan                           # breathing missing for 30 minutes
    lab = label_segment(seg(rr=rr))
    assert lab.valid[14] and not lab.valid[15] and not lab.valid[45]   # row 15 sees only 14 breathing minutes ahead
    assert lab.valid[70]


def test_events_are_fresh_only():
    sp = np.full(160, 97.0)
    sp[40:46] = 88
    sp[60:66] = 88                               # re-entry within 30 minutes of the first event's end (45)
    sp[120:126] = 88
    lab = label_segment(seg(n=160, sp=sp))
    assert [(a, z) for a, z, _ in lab.events] == [(40, 45), (120, 125)]
