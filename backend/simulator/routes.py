"""HTTP side of the simulator. Handlers are async because starting a run needs the event loop."""
from fastapi import APIRouter, HTTPException

from backend.contracts import Model
from backend.simulator.controller import NoScenario, RunInProgress, RunStatus, SimController, UnknownProfile


class StartRequest(Model):
    profile_id: str
    patient_id: str | None = None
    wearable_id: int | None = None


class SkipRequest(Model):
    minutes: float


def build_router(controller: SimController) -> APIRouter:
    router = APIRouter(prefix="/sim")

    @router.get("/profiles")
    async def list_profiles():
        return [{"id": p.id, "name": p.name, "tier": p.tier} for p in controller.profiles()]

    @router.get("/profiles/{profile_id}")
    async def get_profile(profile_id: str):
        """The sample patient's I2 record, to prefill the intake form."""
        try:
            return controller.profile(profile_id).record.model_dump(mode="json", exclude_none=True)
        except UnknownProfile:
            raise HTTPException(404, f"unknown sample patient {profile_id!r}") from None

    @router.get("/run")
    async def run_status() -> RunStatus:
        return controller.status()

    @router.post("/run", status_code=202)
    async def start_run(req: StartRequest) -> RunStatus:
        try:
            return controller.start(req.profile_id, req.patient_id, req.wearable_id)
        except UnknownProfile:
            raise HTTPException(404, f"unknown sample patient {req.profile_id!r}") from None
        except RunInProgress:
            raise HTTPException(409, "a run is already going; stop or reset it first") from None

    @router.post("/scenario", status_code=202)
    async def start_scenario() -> RunStatus:
        try:
            return await controller.start_scenario()
        except RunInProgress:
            raise HTTPException(409, "a run is already going; stop or reset it first") from None

    @router.post("/skip")
    async def skip(req: SkipRequest) -> RunStatus:
        try:
            return await controller.skip(req.minutes)
        except NoScenario:
            raise HTTPException(409, "no scenario is running") from None

    @router.post("/run/stop")
    async def stop_run() -> RunStatus:
        return await controller.stop()

    @router.post("/run/reset")
    async def reset_run() -> RunStatus:
        return await controller.reset()

    return router
