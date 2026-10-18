import asyncio

from fakes import FakeSink
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import SimulatorConfig
from backend.contracts import IntakeRecord
from backend.simulator.controller import SimController
from backend.simulator.routes import build_router


class Held:
    """Fake sleep that never returns, so a started run stays running between requests."""

    async def sleep(self, delay):
        if delay > 0:
            await asyncio.Event().wait()
        await asyncio.sleep(0)


def client():
    c = SimController(FakeSink(), cfg=SimulatorConfig(run_length_s=5), now=lambda: 0.0, sleep=Held().sleep)
    app = FastAPI()
    app.include_router(build_router(c))
    return TestClient(app)


def test_a_sample_patient_comes_back_as_an_i2_record_for_the_form():
    with client() as http:
        listing = http.get("/sim/profiles").json()
        assert [p["id"] for p in listing] == ["h1", "h2", "u1", "u2", "c1", "c2"]
        body = http.get("/sim/profiles/c2").json()
        assert IntakeRecord(**body).triage.alertness == "new_confusion"
        assert http.get("/sim/profiles/nope").status_code == 404


def test_run_lifecycle_over_http():
    with client() as http:
        assert http.post("/sim/run", json={"profile_id": "nope"}).status_code == 404
        started = http.post("/sim/run", json={"profile_id": "u1"})
        assert started.status_code == 202 and started.json()["state"] == "running"
        assert http.get("/sim/run").json() == {"state": "running", "profile_id": "u1", "patient_id": "sim-u1",
                                           "kind": "single", "sim_now": None}
        assert http.post("/sim/run", json={"profile_id": "h1"}).status_code == 409
        assert http.post("/sim/run/stop").json()["state"] == "ended"
        assert http.post("/sim/run/reset").json() == {"state": "live", "profile_id": None, "patient_id": None,
                                                       "kind": None, "sim_now": None}
