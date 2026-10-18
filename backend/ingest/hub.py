"""Dashboard socket: pushes I8, I9, I10, I13, I14 to every client and takes I11 and I12.
A new client first gets the latest state, so a refresh or reconnect never shows blanks."""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable

from starlette.websockets import WebSocketDisconnect

from backend.contracts import Acknowledgment, Model, ScenarioTrigger
from backend.ingest.wire import BadMessage, parse_envelope

log = logging.getLogger(__name__)

SNAPSHOT_TYPES = {"I8", "I9", "I13", "I14"}  # latest value per patient is enough for these


@dataclass(eq=False)  # identity hashing, so clients can live in a set
class _Client:
    queue: asyncio.Queue
    warned: bool = False


class DashboardHub:
    def __init__(self, on_ack: Callable[[Acknowledgment], None],
                 on_scenario: Callable[[ScenarioTrigger], None], queue_max: int = 200):
        self._on_ack, self._on_scenario, self._queue_max = on_ack, on_scenario, queue_max
        self._latest: dict[tuple[str, str | None], dict] = {}
        self._alerts: dict[str, dict] = {}
        self._clients: set[_Client] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, type_: str, model: Model) -> None:
        env = {"type": type_, "data": model.model_dump(mode="json")}
        if type_ in SNAPSHOT_TYPES:
            self._latest[(type_, env["data"].get("patient_id"))] = env
        elif type_ == "I10" and env["data"].get("alert_id"):
            for old in env["data"].get("supersedes") or []:
                self._alerts.pop(old, None)
            self._alerts[env["data"]["alert_id"]] = env
        for c in self._clients:
            self._put(c, env)

    def _snapshot(self) -> list[dict]:
        return [*self._latest.values(), *self._alerts.values()]

    def _put(self, c: _Client, env: dict) -> None:
        if c.queue.full():
            c.queue.get_nowait()
            if not c.warned:
                c.warned = True
                log.warning("dashboard client is slow; dropping its oldest messages")
        c.queue.put_nowait(env)

    async def serve(self, ws) -> None:
        await ws.accept()
        snap = self._snapshot()
        # Sized for the snapshot too, so connecting never drops part of it.
        c = _Client(asyncio.Queue(self._queue_max + len(snap)))
        for env in snap:
            c.queue.put_nowait(env)
        self._clients.add(c)  # no await between snapshot and registering, so nothing is missed or doubled
        tasks = [asyncio.create_task(self._write(ws, c)), asyncio.create_task(self._read(ws))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.cancelled() and t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                    log.warning("dashboard connection ended: %r", t.exception())
        finally:
            for t in tasks:
                t.cancel()
            self._clients.discard(c)

    async def _write(self, ws, c: _Client) -> None:
        while True:
            await ws.send_text(json.dumps(await c.queue.get()))

    async def _read(self, ws) -> None:
        while True:
            text = await ws.receive_text()
            try:
                type_, model = parse_envelope(text, {"I11", "I12"})
                (self._on_ack if type_ == "I11" else self._on_scenario)(model)
            except BadMessage as e:
                log.warning("dashboard message ignored: %s", e)
            except Exception:
                log.exception("dashboard handler failed")
