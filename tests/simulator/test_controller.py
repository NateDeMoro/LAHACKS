import asyncio

import pytest
from fakes import FakeSink

from backend.config import SimulatorConfig
from backend.simulator.controller import RunInProgress, SimController, UnknownProfile

CFG = SimulatorConfig(run_length_s=5, preroll_minutes=60, default_wearable_id=3)


class Gate:
    """Fake sleep: any real wait blocks until the gate opens, so a run can be held mid-way."""

    def __init__(self, open_=False):
        self._open = asyncio.Event()
        if open_:
            self._open.set()

    def open(self):
        self._open.set()

    async def sleep(self, delay):
        if delay > 0:
            await self._open.wait()
        await asyncio.sleep(0)


def controller(gate, sink=None):
    return SimController(sink or FakeSink(), cfg=CFG, now=lambda: 0.0, sleep=gate.sleep)


async def test_a_run_plays_the_sample_patient_start_to_finish():
    sink = FakeSink()
    c = controller(Gate(open_=True), sink)
    c.start("u1")
    await c.wait()
    assert len(sink.readings()) == CFG.run_length_s
    assert {r.wearable_id for r in sink.readings()} == {3}
    seed = next(call for call in sink.calls if call[0] == "seed")
    assert seed[1] == "sim-u1" and len(seed[2]) == CFG.preroll_minutes
    assert sink.states() == ["running", "ended"]
    assert c.status().state == "ended" and c.status().profile_id == "u1"


def test_an_unknown_profile_is_rejected():
    with pytest.raises(UnknownProfile):
        controller(Gate()).start("nope")


async def test_a_second_start_is_rejected_while_a_run_is_going():
    c = controller(Gate())
    c.start("h1")
    with pytest.raises(RunInProgress):
        c.start("h2")
    await c.stop()


async def test_stop_ends_the_run_and_a_new_one_can_start():
    gate, sink = Gate(), FakeSink()
    c = controller(gate, sink)
    c.start("h1")
    await asyncio.sleep(0.01)  # let the first reading out; the gate holds the rest
    await c.stop()
    assert c.status().state == "ended"
    assert len(sink.readings()) == 1 and sink.states()[-1] == "ended"
    gate.open()
    c.start("h2")
    await c.wait()
    assert len(sink.readings()) == 1 + CFG.run_length_s


async def test_reset_cancels_a_running_run_and_returns_to_live():
    sink = FakeSink()
    c = controller(Gate(), sink)
    c.start("c2")
    await asyncio.sleep(0.01)
    await c.reset()
    assert c.status().state == "live" and c.status().profile_id is None
    assert sink.calls[-1] == ("state", "sim-c2", "live")


async def test_start_takes_the_patient_and_wearable_from_intake():
    sink = FakeSink()
    c = controller(Gate(open_=True), sink)
    c.start("h1", patient_id="p-9", wearable_id=7)
    await c.wait()
    assert {r.wearable_id for r in sink.readings()} == {7}
    assert next(call for call in sink.calls if call[0] == "seed")[1] == "p-9"
    assert c.status().patient_id == "p-9"


async def test_a_finished_run_can_be_followed_by_another():
    sink = FakeSink()
    c = controller(Gate(open_=True), sink)
    c.start("u1")
    await c.wait()
    c.start("c1")
    await c.wait()
    assert len(sink.readings()) == 2 * CFG.run_length_s
    assert sink.states() == ["running", "ended", "running", "ended"]


async def test_stop_right_after_start_leaves_the_controller_usable():
    sink = FakeSink()
    c = controller(Gate(open_=True), sink)
    c.start("h1")
    await c.stop()  # cancelled before the run's first step
    assert c.status().state == "ended" and sink.readings() == []
    c.start("h2")
    await c.wait()
    assert len(sink.readings()) == CFG.run_length_s


async def test_a_start_that_lands_while_stop_is_finishing_keeps_running():
    c = controller(Gate())
    c.start("h1")
    await asyncio.sleep(0.01)
    stopping = asyncio.create_task(c.stop())
    while c.status().state == "running":  # the old run is done but stop has not returned yet
        await asyncio.sleep(0)
    c.start("h2")
    await stopping
    assert c.status().state == "running" and c.status().profile_id == "h2"
    await c.stop()


async def test_a_start_that_lands_while_reset_is_finishing_is_not_wiped():
    sink = FakeSink()
    c = controller(Gate(), sink)
    c.start("h1")
    await asyncio.sleep(0.01)
    resetting = asyncio.create_task(c.reset())
    while c.status().state == "running":
        await asyncio.sleep(0)
    c.start("h2")
    await resetting
    assert c.status().state == "running" and c.status().profile_id == "h2"
    assert "live" not in sink.states()
    await c.stop()


async def test_a_bad_length_does_not_wedge_the_controller():
    c = controller(Gate(open_=True))
    with pytest.raises(ValueError):
        c.start("h1", length_s=1)
    assert c.status().state == "live"
    c.start("h1")
    await c.wait()
    assert c.status().state == "ended"


async def test_a_failing_sink_ends_the_run_without_crashing():
    class FailsOnSecondReading(FakeSink):
        def ingest(self, reading, source):
            super().ingest(reading, source)
            if len(self.readings()) == 2:
                raise RuntimeError("sink down")

    sink = FailsOnSecondReading()
    c = controller(Gate(open_=True), sink)
    c.start("h1")
    await c.wait()
    assert c.status().state == "ended"
    assert sink.states() == ["running", "ended"] and len(sink.readings()) == 2
