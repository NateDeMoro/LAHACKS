import asyncio
import dataclasses
import json
from datetime import UTC, datetime

import pytest
from websockets.asyncio.server import serve

from backend.config import ReceiverConfig
from backend.contracts import VitalsReading
from receiver.sender import QUEUE_MAX, IngestSender


def reading(hr=70.0, **kw):
    return VitalsReading(wearable_id=1, ts=datetime(2026, 1, 1, tzinfo=UTC), hr=hr, **kw)


async def fast_sleep(delay):
    await asyncio.sleep(0.01)


async def until(pred, timeout=3.0):
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.001)


@pytest.fixture
async def started():
    tasks = []

    def start(sender):
        tasks.append(asyncio.create_task(sender.run()))

    yield start
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


class Server:
    def __init__(self):
        self.received = []
        self.port = 0
        self._server = None

    async def _handler(self, ws):
        async for msg in ws:
            self.received.append(msg)

    async def start(self):
        self._server = await serve(self._handler, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self._server.close(close_connections=True)
        await self._server.wait_closed()

    def make_sender(self, **kw):
        cfg = dataclasses.replace(ReceiverConfig(), ingest_url=f"ws://127.0.0.1:{self.port}")
        return IngestSender(cfg, sleep=fast_sleep, **kw)


@pytest.fixture
async def server():
    s = Server()
    await s.start()
    yield s
    await s.stop()


async def test_reading_goes_out_as_one_i1_json_message(server, started):
    sender = server.make_sender()
    started(sender)
    await until(lambda: sender.connected)

    assert sender.send(reading(hr=71.5, rr_intervals_ms=[800, 810], contact=True)) is True
    await until(lambda: server.received)

    assert json.loads(server.received[0]) == {
        "type": "I1",
        "data": {
            "wearable_id": 1,
            "ts": "2026-01-01T00:00:00Z",
            "hr": 71.5,
            "rr_intervals_ms": [800, 810],
            "contact": True,
        },
    }


async def test_drops_while_down_and_never_replays_after_server_restart(server, started):
    sender = server.make_sender()
    started(sender)
    await until(lambda: sender.connected)
    sender.send(reading(hr=1))
    await until(lambda: len(server.received) == 1)

    await server.stop()
    await until(lambda: not sender.connected)
    assert sender.send(reading(hr=2)) is False

    await server.start()
    await until(lambda: sender.connected)
    sender.send(reading(hr=3))
    await until(lambda: len(server.received) == 2)

    assert [json.loads(m)["data"]["hr"] for m in server.received] == [1, 3]


class FakeWS:
    """Socket whose send blocks until released; fail() makes it die like a lost connection."""

    def __init__(self):
        self.sent = []
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.failing = False

    async def send(self, msg):
        await self.release.wait()
        if self.failing:
            raise ConnectionError("lost")
        self.sent.append(msg)

    def __aiter__(self):
        return self._wait_closed()

    async def _wait_closed(self):
        await self.closed.wait()
        return
        yield

    def fail(self):
        self.failing = True
        self.release.set()


class FakeConnect:
    def __init__(self):
        self.sockets = []

    def __call__(self, url):
        ws = FakeWS()
        self.sockets.append(ws)
        return _Ctx(ws)


class _Ctx:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


async def test_slow_socket_keeps_only_the_newest_readings_and_send_never_blocks(started):
    fake = FakeConnect()
    sender = IngestSender(ReceiverConfig(), connect=fake, sleep=fast_sleep)
    started(sender)
    await until(lambda: sender.connected)

    total = QUEUE_MAX * 5
    for i in range(total):
        assert sender.send(reading(hr=float(i))) is True  # socket is stuck; this must still return
    fake.sockets[0].release.set()
    sent = fake.sockets[0].sent
    await until(lambda: sent and json.loads(sent[-1])["data"]["hr"] == total - 1)

    assert len(fake.sockets[0].sent) <= QUEUE_MAX + 1  # backlog plus the one already in flight


async def test_readings_queued_before_a_disconnect_are_discarded(started):
    fake = FakeConnect()
    sender = IngestSender(ReceiverConfig(), connect=fake, sleep=fast_sleep)
    started(sender)
    await until(lambda: sender.connected)
    for i in range(5):
        sender.send(reading(hr=float(i)))
    fake.sockets[0].fail()
    await until(lambda: len(fake.sockets) == 2 and sender.connected)

    fake.sockets[1].release.set()
    sender.send(reading(hr=99.0))
    await until(lambda: fake.sockets[1].sent)

    assert [json.loads(m)["data"]["hr"] for m in fake.sockets[1].sent] == [99.0]


async def test_connection_errors_are_retried_with_backoff(started, caplog):
    attempts = []
    sleeps = []

    def flaky_connect(url):
        attempts.append(url)
        if len(attempts) <= 3:
            raise OSError("refused")
        return _Ctx(FakeWS())

    async def record_sleep(delay):
        sleeps.append(delay)
        await asyncio.sleep(0.001)

    cfg = dataclasses.replace(ReceiverConfig(), reconnect_backoff_s=(1.0, 3.0))
    sender = IngestSender(cfg, connect=flaky_connect, sleep=record_sleep)
    started(sender)
    await until(lambda: sender.connected)

    assert sleeps == [1.0, 2.0, 3.0]
    assert "refused" in caplog.text
    assert sender.send(reading()) is True
