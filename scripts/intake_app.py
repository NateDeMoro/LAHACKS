"""Dev stand-in app for S5: intake routes + simulator routes + a RiskEngine, until S2's real app exists.
Use when trying the intake backend by hand or checking it after a change.
Usage:
  uv run python -m scripts.intake_app --selftest                          # offline, stub LLM
  uv run --env-file .env python -m scripts.intake_app [--port 8001]       # live, real StepFun key"""
import argparse
import dataclasses
import threading
import time

from fastapi import FastAPI

from backend.adjuster import adjuster as A
from backend.config import CONFIG, BedConfig, LlmConfig
from backend.intake import routes as intake_routes
from backend.intake.service import IntakeService
from backend.risk_engine.engine import RiskEngine
from backend.simulator import routes as sim_routes
from backend.simulator.controller import SimController


class PrintSink:
    """Run sink that prints instead of feeding ingest (S2 replaces it)."""

    def ingest(self, reading, source):
        pass

    def set_run_state(self, patient_id, state):
        print(f"[sink] {patient_id} run state {state}")

    def seed_trend_history(self, patient_id, rows):
        print(f"[sink] seeded {len(rows)} trend rows for {patient_id}")


def build_app(adjust_fn=A.adjust, cfg=CONFIG, verbose=True):
    engine = RiskEngine()
    if verbose:
        engine.ranges_listener = lambda r: print(f"[I8] {r.patient_id} hr {r.hr.danger_high} "
                                                 f"rr {r.resp_rate.danger_high} temp {r.temp_c.danger_high}")
    service = IntakeService(engine, (lambda a: print(f"[I3] wearable {a.wearable_id} -> {a.patient_id}"))
                            if verbose else (lambda a: None), cfg=cfg, adjust_fn=adjust_fn)
    app = FastAPI()
    app.include_router(intake_routes.build_router(service))
    app.include_router(sim_routes.build_router(SimController(PrintSink())))
    return app, engine, service


def selftest():
    from fastapi.testclient import TestClient
    from scripts.score_adjuster import reply, stub

    llm = LlmConfig(api_key="stub")
    off = dict(use_cache=False, write_log=False)
    gate = threading.Event()

    def adjust_fn(ctx):
        text = ctx.chief_complaint or ""
        if "SLOW" in text:
            assert gate.wait(10)
        body = reply(("suspected_infection", "Fever and chills")) if "chills" in text else reply()
        return A.adjust(ctx, client=stub(body), cfg=llm, **off)

    two_beds = dataclasses.replace(CONFIG, beds=BedConfig(labels={1: "Bed 4", 2: "Bed 5"}))
    app, engine, service = build_app(adjust_fn, two_beds, verbose=False)
    seen = []
    engine.ranges_listener = seen.append

    def wait_done(c, pid):
        for _ in range(100):
            card = c.get(f"/intake/{pid}").json()
            if card["adjuster"] != "pending":
                return card
            time.sleep(0.05)
        raise AssertionError("adjuster stayed pending")

    with TestClient(app) as c:
        u1 = c.get("/sim/profiles/u1").json()
        assert c.get("/intake/wearer").json()["patient_id"] == "demo-001"
        assert [w["wearable_id"] for w in c.get("/intake/wearables").json()] == [1, 2]
        # U1: I3 back, structured limits at once, full result after the background step
        r = c.post("/intake", json={**u1, "wearable_id": 1, "pregnant": None})
        assert r.status_code == 200 and r.json()["wearable_id"] == 1, r.text
        pid = r.json()["patient_id"]
        assert engine.ranges[pid].temp_c.danger_high == 37.8 and engine.ranges[pid].hr.danger_high == 110
        card = wait_done(c, pid)
        assert card["adjuster"] == "done" and engine.ranges[pid].resp_rate.danger_high == 22, card["adjuster"]
        assert {i["rule_id"] for i in card["i15_items"]} == {"age65", "beta_blocker", "suspected_infection"}
        assert card["context"]["drug_classes"] == ["beta_blocker"] and card["context"]["bmi"] == 31.8
        assert len(seen) >= 2  # ranges pushed after each on_intake
        # quick resubmit: the slow first call must not overwrite the newer intake
        h1 = c.get("/sim/profiles/h1").json()
        c.post("/intake", json={**h1, "wearable_id": 2, "chief_complaint": "SLOW chills and fever"})
        c.post("/intake", json={**h1, "wearable_id": 2, "chief_complaint": "Rolled my ankle."})
        card = wait_done(c, h1["patient_id"])
        gate.set()
        for _ in range(100):
            if service.stale_dropped:
                break
            time.sleep(0.05)
        assert service.stale_dropped == 1
        card = c.get(f"/intake/{h1['patient_id']}").json()
        assert card["adjuster"] == "done" and card["i15_items"] == []
        assert engine.ranges[h1["patient_id"]].resp_rate.danger_high != 22
        # moving a patient to another bed frees the first
        c.post("/intake", json={**u1, "wearable_id": 2, "pregnant": None})
        owners = {w["wearable_id"]: w["patient_id"] for w in c.get("/intake/wearables").json()}
        assert owners == {1: None, 2: pid}, owners
        wait_done(c, pid)
        # a missing or unknown wearable is a 422; a missing patient is a 404; no id gets a generated one
        assert c.post("/intake", json={**u1, "wearable_id": 9}).status_code == 422
        assert c.post("/intake", json={**u1, "wearable_id": None}).status_code == 422
        assert c.get("/intake/nobody").status_code == 404
        gen = c.post("/intake", json={"wearable_id": 1, "age": 40}).json()["patient_id"]
        assert gen.startswith("pt-")
        wait_done(c, gen)
        # on_intake raising in the background apply is logged and the card reports structured only
        real, calls = engine.on_intake, []

        def flaky(ctx, i5):
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError("boom")
            return real(ctx, i5)

        engine.on_intake = flaky
        bad = c.post("/intake", json={"wearable_id": 1, "age": 50}).json()["patient_id"]
        card = wait_done(c, bad)
        engine.on_intake = real
        assert card["adjuster"] == "structured only" and len(calls) == 2, card["adjuster"]
    print("selftest passed: I3 out, structured limits at once, full I5 after background, stale result dropped, background apply error caught, bed move frees old, 422/404")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--port", type=int, default=8001)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    import uvicorn
    app, _, _ = build_app()
    uvicorn.run(app, host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
