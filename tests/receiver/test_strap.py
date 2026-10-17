import asyncio
import dataclasses
import logging

import pytest

from backend.config import ReceiverConfig
from receiver.strap import StrapLink


class FakeClient:
    def __init__(self, world, device, disconnected_callback):
        self.world = world
        self.disconnected_callback = disconnected_callback
        self.connect_error = world.connect_errors.pop(0) if world.connect_errors else None
        self.disconnected = False
        world.clients.append(self)

    async def connect(self):
        if self.connect_error:
            raise self.connect_error

    async def disconnect(self):
        self.disconnected = True

    def drop(self):
        self.disconnected_callback(self)


class FakeHeartRate:
    def __init__(self, world, client, callback):
        self.callback = callback
        self.contact_detection = world.contact_detection
        self.good_contact = asyncio.Event()
        self.start_error = world.start_errors.pop(0) if world.start_errors else None
        self.stopped = False
        world.hrs.append(self)

    async def start_notify(self):
        if self.start_error:
            raise self.start_error

    async def stop_notify(self):
        self.stopped = True

    def emit(self, hr=60, rr=(1000,), tstamp=1):
        self.callback(("HR", tstamp, (hr, list(rr)), None))


class World:
    """Scripted stand-ins for bleak and bleakheart."""

    def __init__(self, finds=None):
        self.finds = list(finds) if finds is not None else []
        self.connect_errors = []
        self.start_errors = []
        self.contact_detection = True
        self.clients = []
        self.hrs = []
        self.sleeps = []
        self.frames = []

    async def find_device(self, prefix, timeout):
        self.prefix, self.timeout = prefix, timeout
        item = self.finds.pop(0) if self.finds else "device"
        if isinstance(item, Exception):
            raise item
        return item

    async def sleep(self, delay):
        self.sleeps.append(delay)
        await asyncio.sleep(0.001)

    def make(self, **cfg_overrides):
        cfg = dataclasses.replace(ReceiverConfig(), **cfg_overrides)
        return StrapLink(
            cfg,
            lambda *frame: self.frames.append(frame),
            find_device=self.find_device,
            client_factory=lambda device, disconnected_callback: FakeClient(self, device, disconnected_callback),
            heartrate_factory=lambda client, callback: FakeHeartRate(self, client, callback),
            sleep=self.sleep,
        )


async def until(pred, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.001)


@pytest.fixture
async def started():
    """Start a link's run loop and always cancel it afterwards."""
    tasks = []

    def start(link):
        tasks.append(asyncio.create_task(link.run()))
        return tasks[-1]

    yield start
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize(
    "contact_detection, good, expected",
    [(True, True, True), (True, False, False), (False, True, None), (None, False, None)],
)
async def test_frame_values_and_contact(started, contact_detection, good, expected):
    world = World()
    world.contact_detection = contact_detection
    link = world.make()
    started(link)
    await until(lambda: link.connected)

    hr = world.hrs[0]
    if good:
        hr.good_contact.set()
    hr.emit(hr=72, rr=(810, 790), tstamp=123)

    assert world.frames == [(123, 72, [810, 790], expected)]
    assert world.prefix == ReceiverConfig().strap_name_prefix
    assert world.timeout == ReceiverConfig().scan_timeout_s


async def test_missing_device_backs_off_doubling_up_to_the_cap(started):
    world = World(finds=[None] * 5)
    link = world.make(reconnect_backoff_s=(1.0, 4.0))
    started(link)

    await until(lambda: link.connected)
    assert world.sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


async def test_backoff_resets_after_a_connection_that_delivered_frames(started):
    world = World(finds=[None, None, "device", None, None])
    link = world.make(reconnect_backoff_s=(1.0, 8.0))
    started(link)

    await until(lambda: link.connected)
    world.hrs[0].emit()
    world.clients[0].drop()
    await until(lambda: len(world.sleeps) == 5)

    assert world.sleeps == [1.0, 2.0, 1.0, 2.0, 4.0]


async def test_backoff_keeps_growing_when_a_connection_delivers_nothing(started):
    world = World(finds=["device", "device", None])
    link = world.make(reconnect_backoff_s=(1.0, 8.0), stall_timeout_s=0.02)
    started(link)

    await until(lambda: len(world.sleeps) == 3)
    assert world.sleeps == [1.0, 2.0, 4.0]


async def test_disconnect_triggers_rescan_and_reconnect(started):
    world = World()
    link = world.make()
    started(link)
    await until(lambda: link.connected)

    world.clients[0].drop()
    await until(lambda: len(world.clients) == 2 and link.connected)

    assert world.clients[0].disconnected and world.hrs[0].stopped
    world.hrs[1].emit(hr=80)
    assert world.frames[-1][1] == 80


async def test_stalled_stream_triggers_reconnect(started):
    world = World()
    link = world.make(stall_timeout_s=0.05)
    started(link)
    await until(lambda: link.connected)

    await until(lambda: not link.connected)
    await until(lambda: len(world.clients) == 2)
    assert world.clients[0].disconnected


async def test_steady_frames_prevent_a_stall(started):
    world = World()
    link = world.make(stall_timeout_s=0.1)
    started(link)
    await until(lambda: link.connected)

    for _ in range(8):
        world.hrs[0].emit()
        await asyncio.sleep(0.03)

    assert link.connected and len(world.clients) == 1


async def test_cancel_stops_notifications_and_disconnects():
    world = World()
    link = world.make()
    task = asyncio.create_task(link.run())
    await until(lambda: link.connected)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert world.hrs[0].stopped and world.clients[0].disconnected
    assert not link.connected


@pytest.mark.parametrize("stage", ["scan", "connect", "start_notify"])
async def test_failure_is_logged_and_retried(started, caplog, stage):
    world = World()
    boom = RuntimeError(f"{stage} boom")
    if stage == "scan":
        world.finds = [boom]
    elif stage == "connect":
        world.connect_errors = [boom]
    else:
        world.start_errors = [boom]
    link = world.make()

    with caplog.at_level(logging.WARNING):
        started(link)
        await until(lambda: link.connected)

    assert f"{stage} boom" in caplog.text
    assert world.sleeps[:1] == [1.0]
    if stage != "scan":
        assert world.clients[0].disconnected
