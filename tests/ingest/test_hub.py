import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.contracts import Alert, LiveNews2, LiveWindow, PatientRanges, RiskResult
from backend.ingest.hub import DashboardHub

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone(timedelta(hours=-7)))


def client_for(hub):
    app = FastAPI()

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await hub.serve(sock)

    return TestClient(app)


def hub(**kw):
    return DashboardHub(kw.pop("on_ack", lambda a: None), kw.pop("on_scenario", lambda s: None), **kw)


def test_new_client_gets_latest_per_type_and_patient():
    h = hub()
    h.publish("I13", LiveWindow(patient_id="p1", window_end_ts=T0, hr=70))
    h.publish("I13", LiveWindow(patient_id="p1", window_end_ts=T0 + timedelta(seconds=1), hr=71))
    h.publish("I13", LiveWindow(patient_id="p2", window_end_ts=T0, hr=90))
    h.publish("I14", LiveNews2(patient_id="p1", news2=1))
    h.publish("I9", RiskResult(patient_id="p1", level="safe"))
    h.publish("I8", PatientRanges(patient_id="p1"))
    with client_for(h).websocket_connect("/ws") as ws:
        got = [ws.receive_json() for _ in range(5)]
    by = {(m["type"], m["data"]["patient_id"]): m["data"] for m in got}
    assert set(by) == {("I13", "p1"), ("I13", "p2"), ("I14", "p1"), ("I9", "p1"), ("I8", "p1")}
    assert by[("I13", "p1")]["hr"] == 71


def test_alert_snapshot_drops_superseded_and_keeps_resolved():
    h = hub()
    h.publish("I10", Alert(alert_id="a1", patient_id="p1", severity="urgent"))
    h.publish("I10", Alert(alert_id="a2", patient_id="p1", severity="high", supersedes=["a1"]))
    h.publish("I10", Alert(alert_id="a3", patient_id="p2", severity="warning"))
    h.publish("I10", Alert(alert_id="a3", patient_id="p2", severity="warning", resolved=True))
    with client_for(h).websocket_connect("/ws") as ws:
        got = [ws.receive_json()["data"] for _ in range(2)]
    assert {a["alert_id"]: a["resolved"] for a in got} == {"a2": None, "a3": True}


def test_live_publish_reaches_client_with_nulls_kept():
    h = hub()
    with client_for(h).websocket_connect("/ws") as ws:
        h.publish("I13", LiveWindow(patient_id="p1", hr=70))
        msg = ws.receive_json()
    assert msg["type"] == "I13" and msg["data"]["hr"] == 70 and msg["data"]["spo2"] is None


def test_inbound_messages_dispatch_and_bad_ones_are_ignored():
    acks, runs = [], []

    def boom(_):
        raise RuntimeError("handler failed")

    h = hub(on_ack=lambda a: acks.append(a.alert_id), on_scenario=lambda s: runs.append(s.scenario_id))
    with client_for(h).websocket_connect("/ws") as ws:
        ws.send_text("garbage")
        ws.send_text('{"type":"I13","data":{}}')  # valid interface, but not one the dashboard may send
        ws.send_text('{"type":"I12","data":{"scenario_id":"u1","patient_id":"p1"}}')
        ws.send_text('{"type":"I11","data":{"alert_id":"a1"}}')
        h.publish("I13", LiveWindow(patient_id="p1"))
        ws.receive_json()  # round trip: socket still open and all earlier messages were handled
    assert acks == ["a1"] and runs == ["u1"]

    h = hub(on_ack=boom)
    with client_for(h).websocket_connect("/ws") as ws:
        ws.send_text('{"type":"I11","data":{"alert_id":"a1"}}')
        h.publish("I13", LiveWindow(patient_id="p1"))
        assert ws.receive_json()["type"] == "I13"


class FakeSocket:
    """Send blocks until released, so a slow client can be simulated."""

    def __init__(self):
        self.gate, self.sent, self.closed = asyncio.Event(), [], asyncio.Event()

    async def accept(self):
        pass

    async def send_text(self, text):
        await self.gate.wait()
        self.sent.append(json.loads(text))

    async def receive_text(self):
        await self.closed.wait()
        raise WebSocketDisconnect()


async def test_slow_client_loses_oldest_and_disconnect_cleans_up():
    h = hub(queue_max=2)
    sock = FakeSocket()
    task = asyncio.create_task(h.serve(sock))
    await asyncio.sleep(0)
    h.publish("I13", LiveWindow(patient_id="p", hr=1))
    await asyncio.sleep(0)  # writer takes the first message and blocks sending it
    for hr in (2, 3, 4):
        h.publish("I13", LiveWindow(patient_id="p", hr=hr))
    sock.gate.set()
    await asyncio.sleep(0.01)
    assert [m["data"]["hr"] for m in sock.sent] == [1, 3, 4]
    assert h.client_count == 1
    sock.closed.set()
    await asyncio.wait_for(task, 1)
    assert h.client_count == 0
    h.publish("I13", LiveWindow(patient_id="p", hr=5))  # no client left; must not raise
