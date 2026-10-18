"""Backend app: ingest socket, dashboard socket, simulator and intake routes, and the loops that run them.
Run: uv run --env-file .env uvicorn backend.app:create_app --factory"""
import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend.config import CONFIG
from backend.timeutil import now_la
from backend.contracts import ScenarioTrigger
from backend.ingest.hub import DashboardHub
from backend.ingest.service import IngestService
from backend.ingest.store import Store
from backend.ingest.tiger import TigerMirror, build_router as build_tiger_router
from backend.ingest.wire import BadMessage, parse_envelope
from backend.intake.routes import build_router as build_intake_router
from backend.intake.service import IntakeService
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine
from backend.simulator.controller import RunInProgress, SimController, UnknownProfile
from backend.patients.registry import PatientRegistry
from backend.patients.routes import build_router as build_patients_router
from backend.simulator.routes import build_router
from backend.simulator.scenario import ScenarioRunner

log = logging.getLogger(__name__)


def create_app(engine: RiskEngine | None = None, store_path: str | Path | None = None) -> FastAPI:
    engine = engine or RiskEngine()
    alerts = AlertLogic(engine.config.alerts, engine.bed_label)
    store = Store(store_path or CONFIG.ingest.store_path)
    tiger = TigerMirror(CONFIG.ingest.tiger_data_url) if CONFIG.ingest.tiger_data_url else None
    sink = store
    if tiger:
        class FanOut:  # IngestService only calls write()
            def write(self, *args, **kwargs):
                store.write(*args, **kwargs)
                tiger.write(*args, **kwargs)
        sink = FanOut()
    hub_ref: list[DashboardHub] = []  # the service needs hub.publish and the hub needs service.on_ack
    registry = PatientRegistry()
    service = IngestService(engine, alerts, lambda t, m: hub_ref[0].publish(t, m), sink,
                            on_drop=lambda pid: hub_ref[0].forget(pid), on_risk=registry.add_history)
    sim_wearables = set(CONFIG.simulator.scenario_wearable_ids)
    agent_fns = {}
    if CONFIG.agents.enabled:  # the adjuster and condition steps run in the Fetch.ai agents, in-process on failure
        from backend.agent_bridge import AgentBridge, agent_fns as make_fns
        bridge = AgentBridge()
        bridge.start()
        agent_fns = dict(zip(("adjust_fn", "condition_fn"), make_fns(bridge)))
    intake = IntakeService(engine, lambda a: service.assign(a.wearable_id, a.patient_id),
                           on_submit=lambda ctx: registry.upsert(ctx, engine.bed_label(ctx.patient_id),
                                                                 ctx.wearable_id in sim_wearables), **agent_fns)
    scenario = ScenarioRunner(service, intake, registry)
    controller = SimController(service, scenario=scenario)

    def start_run(trigger: ScenarioTrigger) -> None:
        try:
            controller.start(trigger.scenario_id, trigger.patient_id, service.wearable_of(trigger.patient_id))
        except (UnknownProfile, RunInProgress) as e:
            log.warning("run %s not started: %r", trigger.scenario_id, e)

    hub = DashboardHub(service.on_ack, start_run, queue_max=2000)  # room for a 20-minute lead-in plus a skip
    hub_ref.append(hub)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        tasks = [asyncio.create_task(store.run()), asyncio.create_task(service.run())]
        if tiger:
            tasks.append(asyncio.create_task(tiger.run()))
        try:
            yield
        finally:
            await controller.stop()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_router(controller))
    app.include_router(build_intake_router(intake))
    if tiger:
        app.include_router(build_tiger_router(tiger))

    def call_in(patient_id: str) -> None:
        if registry.get(patient_id).simulated:
            scenario.call_in(patient_id)
        else:
            registry.mark_called_in(patient_id, now_la())

    app.include_router(build_patients_router(registry, lambda pid: hub.open_alerts(pid), call_in))

    @app.websocket("/ws/ingest")
    async def ws_ingest(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                try:
                    _, reading = parse_envelope(await ws.receive_text(), {"I1"})
                except BadMessage as e:
                    log.warning("ingest message ignored: %s", e)  # keep the socket: a reconnect shows on the demo
                    continue
                service.ingest(reading, "strap")
        except WebSocketDisconnect:
            pass

    @app.websocket("/ws/dashboard")
    async def ws_dashboard(ws: WebSocket):
        await hub.serve(ws)

    return app
