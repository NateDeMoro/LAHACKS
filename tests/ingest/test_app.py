import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(store_path=tmp_path / "ingest.sqlite")) as c:
        yield c


def i1(**v):
    return json.dumps({"type": "I1", "data": {"wearable_id": 1, "contact": True, **v}})


def until(ws, type_, pred=lambda d: True, limit=40):
    """Read dashboard messages until one of this type matches; the 1 Hz tick makes one arrive."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == type_ and pred(msg["data"]):
            return msg["data"]
    raise AssertionError(f"no {type_} matched in {limit} messages")


def test_strap_readings_reach_the_dashboard_as_a_live_window(client):
    with client.websocket_connect("/ws/dashboard") as dash, client.websocket_connect("/ws/ingest") as ing:
        ing.send_text(i1(hr=72, resp_rate=15))
        win = until(dash, "I13", lambda d: d["clean_seconds"])
        assert win["patient_id"] == "demo-001" and win["run_state"] == "live"


def test_bad_ingest_messages_are_ignored_and_the_socket_stays_open(client):
    with client.websocket_connect("/ws/dashboard") as dash, client.websocket_connect("/ws/ingest") as ing:
        ing.send_text("not json")
        ing.send_text(json.dumps({"type": "I1", "data": {"hr": 70, "bogus": 1}}))
        ing.send_text('{"type": "I1", "data": {"wearable_id": 1, "contact": true, "hr": 72, "spo2": NaN}}')
        win = until(dash, "I13", lambda d: d["clean_seconds"])  # the NaN reading got through with spo2 null
        assert win["spo2"] is None


def test_run_button_starts_a_simulated_run_through_the_same_path(client):
    with client.websocket_connect("/ws/dashboard") as dash:
        dash.send_text(json.dumps({"type": "I12", "data": {"scenario_id": "h1", "patient_id": "demo-001"}}))
        win = until(dash, "I13", lambda d: d["run_state"] == "running" and d["clean_seconds"])
        assert win["patient_id"] == "demo-001"
    assert client.get("/sim/run").json()["state"] == "running"
