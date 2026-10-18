from datetime import datetime, timedelta

import pytest

from backend.config import IngestConfig
from backend.contracts import VitalsReading
from backend.ingest.stream import PatientStream
from backend.timeutil import LA

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=LA)


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def strap(hr=70.0, rr=15.0, contact=True) -> VitalsReading:
    return VitalsReading(wearable_id=1, hr=hr, resp_rate=rr, contact=contact)


def sim(**v) -> VitalsReading:
    return VitalsReading(wearable_id=1, contact=True, **v)


def run_live(stream, seconds, reading=strap, start=1):
    """Feed one strap reading and one tick per second; returns the ticks."""
    out = []
    for s in range(start, start + seconds):
        stream.on_reading(at(s), reading(), "strap")
        out.append(stream.tick(at(s)))
    return out


def test_window_median_waits_for_min_samples():
    st = PatientStream("p1", at(0))
    ticks = run_live(st, 6)
    assert ticks[3].live.hr is None  # 4 samples
    assert ticks[4].live.hr == 70  # 5th
    assert ticks[5].live.clean_seconds == 6


def test_window_keeps_only_the_last_30_seconds():
    st = PatientStream("p1", at(0))
    for s in range(1, 16):
        st.on_reading(at(s), strap(hr=100), "strap")
        st.tick(at(s))
    ticks = run_live(st, 40, lambda: strap(hr=60), start=16)
    assert ticks[-1].live.hr == 60
    assert ticks[-1].live.clean_seconds == 30


def test_no_contact_seconds_are_not_clean_and_drain_the_window():
    st = PatientStream("p1", at(0))
    run_live(st, 10)
    ticks = run_live(st, 3, lambda: strap(hr=None, rr=None, contact=False), start=11)
    assert ticks[-1].live.clean_seconds == 10  # the three no-contact seconds do not count
    assert ticks[-1].live.hr == 70
    # With the strap gone entirely, readings go stale and the window empties after 30 s.
    last = None
    for s in range(14, 80):
        last = st.tick(at(s))
    assert last.live.hr is None and last.live.clean_seconds == 0


def test_simulator_value_lapses_after_its_ttl():
    st = PatientStream("p1", at(0), IngestConfig(min_samples=7))
    st.on_reading(at(1), sim(spo2=96), "simulator")
    for s in range(1, 14):
        st.on_reading(at(s), strap(), "strap")
        t = st.tick(at(s))
    assert t.live.hr == 70
    assert t.live.spo2 is None  # fresh for seconds 1-6 only, so six samples, below the seven needed


def test_simulator_overrides_strap_for_the_same_vital():
    st = PatientStream("p1", at(0))
    for s in range(1, 7):
        st.on_reading(at(s), strap(hr=70), "strap")
        st.on_reading(at(s), sim(hr=120), "simulator")
        t = st.tick(at(s))
    assert t.live.hr == 120


def test_on_reading_says_whether_it_kept_the_reading():
    st = PatientStream("p1", at(0))
    assert st.on_reading(at(1), strap(), "strap") is True
    st.set_run_state(at(1), "running")
    assert st.on_reading(at(2), strap(), "strap") is False
    assert st.on_reading(at(2), sim(hr=90), "simulator") is True
    st.set_run_state(at(3), "ended")
    assert st.on_reading(at(4), sim(hr=90), "simulator") is False


def test_run_mode_drops_strap_readings():
    st = PatientStream("p1", at(0))
    st.set_run_state(at(0), "running")
    for s in range(1, 7):
        st.on_reading(at(s), strap(hr=70), "strap")
        st.on_reading(at(s), sim(hr=90, resp_rate=18, spo2=97, temp_c=37.0), "simulator")
        t = st.tick(at(s))
    assert (t.live.hr, t.live.spo2, t.live.temp_c) == (90, 97, 37.0)
    assert t.live.run_state == "running"


def test_ended_run_freezes_the_window_but_keeps_the_clock_moving():
    st = PatientStream("p1", at(0))
    st.set_run_state(at(0), "running")
    for s in range(1, 8):
        st.on_reading(at(s), sim(hr=90, resp_rate=18, spo2=97, temp_c=37.0), "simulator")
        st.tick(at(s))
    st.set_run_state(at(8), "ended")
    st.on_reading(at(9), sim(hr=200), "simulator")  # ignored once ended
    t = st.tick(at(300))
    assert t.live.hr == 90 and t.live.window_end_ts == at(300) and t.live.run_state == "ended"
    assert t.period is None


def test_reset_to_live_clears_the_window():
    st = PatientStream("p1", at(0))
    st.set_run_state(at(0), "running")
    for s in range(1, 8):
        st.on_reading(at(s), sim(hr=90, resp_rate=18, spo2=97, temp_c=37.0), "simulator")
        st.tick(at(s))
    st.set_run_state(at(8), "live")
    t = st.tick(at(9))
    assert t.live.hr is None and t.live.clean_seconds == 0 and t.live.run_state == "live"


def test_periods_start_at_the_stream_start():
    st = PatientStream("p1", at(100))
    ticks = run_live(st, 65, start=101)
    periods = [t.period for t in ticks if t.period]
    assert [m.period_ts for m in periods] == [at(100), at(130)]
    assert periods[0].hr == 70 and periods[0].clean_seconds == 29  # first tick lands 1 s after the start


def test_period_with_no_clean_data_still_reports_zero_seconds():
    st = PatientStream("p1", at(0))
    periods = [t.period for t in (st.tick(at(s)) for s in range(1, 32)) if t.period]
    assert len(periods) == 1 and periods[0].hr is None and periods[0].clean_seconds == 0


def test_breathing_rate_is_off_for_strap_and_simulator():
    st = PatientStream("p1", at(0))
    ticks = run_live(st, 6)  # the strap sends rr=15
    assert ticks[-1].live.hr == 70 and ticks[-1].live.resp_rate is None
    st.set_run_state(at(6), "running")
    ticks = []
    for s in range(7, 70):
        st.on_reading(at(s), sim(hr=90, resp_rate=18, spo2=97), "simulator")
        ticks.append(st.tick(at(s)))
    assert ticks[-1].live.hr == 90 and ticks[-1].live.spo2 == 97 and ticks[-1].live.resp_rate is None
    periods = [t.period for t in ticks if t.period]
    assert periods and periods[0].hr == 90 and periods[0].resp_rate is None


def test_implausible_values_are_dropped():
    st = PatientStream("p1", at(0))
    ticks = run_live(st, 6, lambda: strap(hr=300))
    assert ticks[-1].live.hr is None and ticks[-1].live.clean_seconds == 0
    for s in range(7, 13):
        st.on_reading(at(s), sim(hr=70, spo2=120), "simulator")
        t = st.tick(at(s))
    assert t.live.hr == 70 and t.live.spo2 is None


def test_custom_config_changes_min_samples():
    st = PatientStream("p1", at(0), IngestConfig(min_samples=2))
    assert run_live(st, 2)[-1].live.hr == 70


def test_late_tick_skips_empty_periods_without_a_burst_of_rows():
    st = PatientStream("p1", at(0))
    run_live(st, 10)
    t = st.tick(at(400))  # loop stalled for over six minutes
    assert t.period is not None
    assert st.tick(at(401)).period is None


def test_jittery_ticks_never_report_more_than_60_clean_seconds():
    st = PatientStream("p1", at(0))
    for i in range(1, 140):
        now = at(i * 0.9)
        st.on_reading(now, strap(), "strap")
        assert st.tick(now).live.clean_seconds <= 60


def test_medians_carry_no_float_noise():
    st = PatientStream("p1", at(0))
    for s in range(1, 9):
        st.on_reading(at(s), sim(hr=70, temp_c=36.6 if s % 2 else 36.7), "simulator")
        t = st.tick(at(s))
    assert t.live.temp_c == 36.65


def test_ending_a_run_hands_back_the_open_period():
    st = PatientStream("p1", at(0))
    st.set_run_state(at(0), "running")
    for s in range(1, 90):  # one full period closes on the way; 29 s are left open
        st.on_reading(at(s), sim(hr=90, resp_rate=18, spo2=97, temp_c=37.0), "simulator")
        st.tick(at(s))
    last = st.set_run_state(at(90), "ended")
    assert last.period_ts == at(60) and last.hr == 90 and last.clean_seconds == 30
    assert st.set_run_state(at(91), "ended") is None  # a repeat finds nothing open


def test_ending_with_nothing_open_returns_nothing():
    st = PatientStream("p1", at(0))
    assert st.set_run_state(at(5), "ended") is None
