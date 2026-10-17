from datetime import datetime, timedelta

import pytest

from backend.config import CONFIG
from backend.contracts import VitalsReading
from backend.timeutil import LA
from receiver.frames import FrameProcessor

CFG = CONFIG.receiver
T0 = 1_800_000_000 * 1_000_000_000  # an arbitrary frame time, in ns
SEC = 1_000_000_000


class FakeEstimator:
    def __init__(self, rate=15.0):
        self.rate = rate
        self.beats = []  # one (beat_times_s, rr_ms) entry per add_beats call
        self.estimate_calls = []
        self.resets = 0

    def add_beats(self, beat_times_s, rr_ms):
        self.beats.append((list(beat_times_s), list(rr_ms)))

    def estimate(self, now_s, contact=True):
        self.estimate_calls.append((now_s, contact))
        return self.rate

    def reset(self):
        self.resets += 1


@pytest.fixture
def est():
    return FakeEstimator()


@pytest.fixture
def proc(est):
    return FrameProcessor(CFG, est)


def test_normal_frame_builds_i1_reading_and_feeds_beats(proc, est):
    r = proc.on_frame(T0, 72, [800, 850], True)

    assert r.wearable_id == CFG.wearable_id
    assert r.hr == 72
    assert r.rr_intervals_ms == [800, 850]
    assert r.contact is True
    assert r.resp_rate == 15.0
    assert r.spo2 is None and r.temp_c is None
    t_end = T0 / 1e9
    (times, rr), = est.beats
    assert times == pytest.approx([t_end - 0.85, t_end])
    assert rr == [800, 850]
    assert est.estimate_calls == [(pytest.approx(t_end), True)]


def test_frame_with_no_beats_is_still_a_reading(proc, est):
    r = proc.on_frame(T0, 70, [], True)

    assert r.hr == 70
    assert r.rr_intervals_ms == []
    assert r.contact is True
    assert all(not times for times, _ in est.beats)  # nothing (or an empty list) fed


def test_ts_is_la_time_of_the_frame(proc):
    r = proc.on_frame(T0, 72, [800], True)

    assert r.ts.utcoffset() is not None
    assert r.ts.utcoffset() in (timedelta(hours=-7), timedelta(hours=-8))
    assert r.ts == datetime.fromtimestamp(T0 / 1e9, LA)
    assert r.ts.tzinfo is LA


def test_sensor_contact_false_nulls_vitals_and_resets_once(proc, est):
    proc.on_frame(T0, 72, [800], True)
    beats_before = len(est.beats)

    for i in range(1, 4):
        r = proc.on_frame(T0 + i * SEC, 72, [800], False)
        assert (r.hr, r.resp_rate, r.rr_intervals_ms, r.contact) == (None, None, [], False)

    assert est.resets == 1
    assert len(est.beats) == beats_before


def test_contact_regained_feeds_beats_again_and_a_new_loss_resets_again(proc, est):
    proc.on_frame(T0, 72, [800], False)
    r = proc.on_frame(T0 + SEC, 72, [800], True)
    assert r.contact is True and r.hr == 72 and r.resp_rate == 15.0
    assert len(est.beats) == 1

    proc.on_frame(T0 + 2 * SEC, 72, [800], False)
    assert est.resets == 2


def test_no_contact_flag_and_hr_zero_means_no_contact(proc, est):
    r = proc.on_frame(T0, 0, [], None)

    assert (r.hr, r.resp_rate, r.rr_intervals_ms, r.contact) == (None, None, [], False)
    assert est.resets == 1


def test_no_contact_flag_with_beats_means_contact(proc):
    r = proc.on_frame(T0, 72, [800], None)

    assert r.contact is True and r.hr == 72


def test_no_contact_flag_not_flagged_before_timeout_at_start(proc):
    timeout_ns = int(CFG.no_beat_timeout_s * SEC)

    r = proc.on_frame(T0, 72, [], None)
    assert r.contact is True
    r = proc.on_frame(T0 + timeout_ns - SEC, 72, [], None)
    assert r.contact is True
    r = proc.on_frame(T0 + timeout_ns + SEC, 72, [], None)
    assert r.contact is False


def test_no_contact_flag_timeout_counts_from_last_beat(proc):
    timeout_ns = int(CFG.no_beat_timeout_s * SEC)
    proc.on_frame(T0, 72, [800], None)

    assert proc.on_frame(T0 + timeout_ns - SEC, 72, [], None).contact is True
    assert proc.on_frame(T0 + timeout_ns + SEC, 72, [], None).contact is False


def test_no_strap_reading_is_all_null_and_resets_once(proc, est):
    proc.on_frame(T0, 72, [800], True)

    r = proc.no_strap(T0 + SEC)
    proc.no_strap(T0 + 2 * SEC)

    assert r.wearable_id == CFG.wearable_id
    assert r.ts == datetime.fromtimestamp((T0 + SEC) / 1e9, LA)
    assert r.contact is False
    assert (r.hr, r.rr_intervals_ms, r.resp_rate, r.spo2, r.temp_c) == (None,) * 5
    assert est.resets == 1


@pytest.mark.parametrize("make", [
    lambda p: p.on_frame(T0, 72, [800, 850], True),
    lambda p: p.on_frame(T0, 0, [], None),
    lambda p: p.no_strap(T0),
])
def test_output_is_valid_i1_and_serializes(proc, make):
    r = make(proc)

    assert VitalsReading.model_validate(r.model_dump()) == r
    assert '"wearable_id"' in r.model_dump_json()


def test_out_of_order_timestamp_does_not_raise(proc):
    proc.on_frame(T0, 72, [800], True)

    r = proc.on_frame(T0 - 10 * SEC, 72, [], True)

    assert isinstance(r, VitalsReading)
