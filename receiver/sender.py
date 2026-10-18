"""Sends vitals readings to the backend over a websocket, dropping them while it is down."""
import asyncio
import logging
from collections import deque

from backend.config import ReceiverConfig
from backend.contracts import VitalsReading, WsMessage
from backend.observability import trace_fields

log = logging.getLogger(__name__)

QUEUE_MAX = 20  # a slow socket loses the oldest readings instead of building a backlog


def _default_connect(url):
    from websockets.asyncio.client import connect

    return connect(url)


class IngestSender:
    def __init__(self, cfg: ReceiverConfig, *, connect=None, sleep=asyncio.sleep):
        self.cfg = cfg
        self._connect = connect or _default_connect
        self._sleep = sleep
        self._queue: deque[str] = deque(maxlen=QUEUE_MAX)
        self._wake = asyncio.Event()
        self.connected = False
        self.dropped = 0

    def send(self, reading: VitalsReading) -> bool:
        if not self.connected:
            return False
        msg = WsMessage(type="I1", data=reading.model_dump(mode="json", exclude_none=True), **trace_fields())
        if len(self._queue) == QUEUE_MAX:
            self.dropped += 1
            if self.dropped % 10 == 1:  # a slow socket drops one a second, so log the first and every tenth
                log.warning("ingest socket is slow, dropping the oldest reading", extra={"dropped_total": self.dropped})
        self._queue.append(msg.model_dump_json(exclude_none=True))  # keeps the wire unchanged when Sentry is off
        self._wake.set()
        return True

    async def run(self) -> None:
        first, longest = self.cfg.reconnect_backoff_s
        backoff = first
        while True:
            try:
                async with self._connect(self.cfg.ingest_url) as ws:
                    self._queue.clear()
                    self.connected = True
                    backoff = first
                    await self._pump(ws)
            except Exception as e:
                log.warning("ingest connection failed: %r", e)
            finally:
                self.connected = False
                self._queue.clear()
            await self._sleep(backoff)
            backoff = min(backoff * 2, longest)

    async def _pump(self, ws) -> None:
        tasks = [asyncio.create_task(self._write(ws)), asyncio.create_task(self._watch_close(ws))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()
        finally:
            for t in tasks:
                t.cancel()

    async def _write(self, ws) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._queue:
                await ws.send(self._queue.popleft())

    async def _watch_close(self, ws) -> None:
        # Reading is what lets the client notice the server closing while we are idle.
        async for _ in ws:
            pass
