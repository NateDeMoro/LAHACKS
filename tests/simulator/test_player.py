import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fakes import FakeSink

from backend.contracts import MinuteSummary
from backend.simulator.models import Sample
from backend.simulator.player import RunPlayer

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-8)))


class Clock:
    """Fake time: sleeping advances it, so runs take no real time."""

    def __init__(self, overshoot=0.0):
        self.t = 0.0
        self.overshoot = overshoot

    def now(self):
        return self.t

    async def sleep(self, delay):
        self.t += delay + (self.overshoot if delay > 0 else 0)
        await asyncio.sleep(0)  # yield, like a real sleep, so a test can cancel mid-run


def samples(n):
    return [Sample(hr=60.0 + i, resp_rate=14.0 + i, spo2=98.0 - i, temp_c=36.5 + i / 10) for i in range(n)]


def summary():
    return MinuteSummary(minute_ts=datetime(2026, 1, 1, tzinfo=UTC), hr=70.0)


async def play(sink, clock, n=5, preroll=()):
    await RunPlayer(sink, now=clock.now, sleep=clock.sleep).play(
        patient_id="p1", wearable_id=7, start_ts=START, samples=samples(n), preroll=list(preroll)
    )


async def test_one_reading_per_sample_spaced_one_second_with_all_fields():
    clock = Clock()
    sink = FakeSink()
    await play(sink, clock, n=4)

    got = sink.readings()
    assert [r.ts for r in got] == [START + timedelta(seconds=i) for i in range(4)]
    assert got[0].ts.utcoffset() == START.utcoffset()
    assert all(c[2] == "simulator" for c in sink.calls if c[0] == "ingest")
    for i, r in enumerate(got):
        s = samples(4)[i]
        assert (r.wearable_id, r.hr, r.resp_rate, r.spo2, r.temp_c, r.contact) == (
            7, s.hr, s.resp_rate, s.spo2, s.temp_c, True,
        )


async def test_seeds_then_runs_then_ends_and_nothing_follows():
    clock = Clock()
    sink = FakeSink()
    rows = [summary()]
    await play(sink, clock, n=3, preroll=rows)

    kinds = [c[0] if c[0] != "state" else c[2] for c in sink.calls]
    assert kinds == ["seed", "running", "ingest", "ingest", "ingest", "ended"]
    assert sink.calls[0] == ("seed", "p1", rows)


async def test_empty_preroll_skips_seeding():
    sink = FakeSink()
    await play(sink, Clock(), n=2)

    assert not any(c[0] == "seed" for c in sink.calls)


async def test_ticks_are_scheduled_from_the_start_so_slow_sleeps_and_sends_do_not_drift():
    clock = Clock(overshoot=0.05)
    sink = FakeSink(clock, ingest_cost=0.1)
    n = 60
    await play(sink, clock, n=n)

    assert len(sink.readings()) == n
    assert clock.t == pytest.approx(n - 1, abs=1.0)


async def test_cancel_mid_run_ends_the_run_and_stops_sending():
    clock = Clock()
    sink = FakeSink()
    task = asyncio.create_task(play(sink, clock, n=100))
    while len(sink.readings()) < 3:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    sent = len(sink.readings())
    await asyncio.sleep(0.01)

    assert sent < 100
    assert len(sink.readings()) == sent
    assert sink.calls[-1] == ("state", "p1", "ended")
