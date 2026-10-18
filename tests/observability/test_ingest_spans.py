import json

import pytest
import sentry_sdk
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.observability import trace_fields
from backend.timeutil import now_la
from tests.ingest.test_app import i1, until
from tests.ingest.test_service import make, seconds


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(store_path=tmp_path / "ingest.sqlite")) as c:
        yield c


def test_health_answers_for_the_uptime_check(client):
    assert client.get("/health").json() == {"ok": True}


def test_ingest_continues_the_receivers_trace(sentry, client):
    with sentry_sdk.start_transaction(op="receiver.reading", name="receiver reading") as sent:
        fields = trace_fields()
    with client.websocket_connect("/ws/dashboard") as dash, client.websocket_connect("/ws/ingest") as ing:
        ing.send_text(json.dumps({**json.loads(i1(hr=72, resp_rate=15, ts=now_la().isoformat())), **fields}))
        until(dash, "I13", lambda d: d["clean_seconds"])
    got = sentry.transactions("ingest reading")[0]
    assert got["contexts"]["trace"]["trace_id"] == sent.trace_id
    assert 0 <= got["contexts"]["trace"]["data"]["strap_to_ingest_s"] < 5


def test_a_reading_without_headers_still_gets_its_own_trace(sentry, client):
    with client.websocket_connect("/ws/dashboard") as dash, client.websocket_connect("/ws/ingest") as ing:
        ing.send_text(i1(hr=72, resp_rate=15))
        until(dash, "I13", lambda d: d["clean_seconds"])
    assert sentry.transactions("ingest reading")


def test_a_senders_unsampled_decision_is_respected(sentry, client):
    with client.websocket_connect("/ws/dashboard") as dash, client.websocket_connect("/ws/ingest") as ing:
        ing.send_text(json.dumps({**json.loads(i1(hr=72, resp_rate=15)),
                                  "sentry_trace": "0123456789abcdef0123456789abcdef-0123456789abcdef-0"}))
        until(dash, "I13", lambda d: d["clean_seconds"])
    assert not sentry.transactions("ingest reading")


def test_the_tick_scores_news2_inside_its_own_transaction(sentry):
    svc, clock, out = make()
    seconds(svc, clock, 3, hr=70, resp_rate=15)
    tick = sentry.transactions("ingest tick")[0]
    assert any(s["op"] == "engine.second" for s in tick["spans"])


def test_a_period_close_is_its_own_transaction_with_the_engine_span(sentry):
    svc, clock, out = make()
    seconds(svc, clock, 31, hr=70, resp_rate=15)
    period = sentry.transactions("engine period")
    assert period and any(s["op"] == "engine.period" for s in period[0]["spans"])
