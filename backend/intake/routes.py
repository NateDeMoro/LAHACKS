"""HTTP side of intake: the calls the S4 intake page makes. Use when wiring the intake form to the backend.
Poll GET /intake/{patient_id} until adjuster is no longer "pending" (4-40 s). To change the complaint,
POST /intake again with the same patient_id. Send pregnant as null unless the question was answered."""
from fastapi import APIRouter, HTTPException

from backend.contracts import IntakeRecord, WearableAssignment
from backend.fixtures import load_intake
from backend.intake.service import IntakeService, UnknownWearable


def _conditions_json(c: dict | None) -> dict | None:
    if c is None:
        return None
    res = c["resolution"]
    return {"state": c["state"], "resolution": res.model_dump(mode="json") if res else None,
            "suggestions": c["suggestions"], "infra_errors": c["infra_errors"]}


def build_router(service: IntakeService) -> APIRouter:
    router = APIRouter(prefix="/intake")

    # /wearer and /wearables are registered before /{patient_id}
    @router.get("/wearer")
    async def wearer():
        """The live wearer's I2 record, to prefill the intake form."""
        return load_intake().model_dump(mode="json", exclude_none=True)

    @router.get("/wearables")
    async def wearables():
        return service.wearables()

    @router.post("")
    async def submit(rec: IntakeRecord) -> WearableAssignment:
        try:
            return await service.submit(rec)
        except UnknownWearable:
            raise HTTPException(422, f"unknown wearable_id {rec.wearable_id!r}") from None

    @router.get("/{patient_id}")
    async def card(patient_id: str):
        c = service.card(patient_id)
        if c is None:
            raise HTTPException(404, f"no intake for {patient_id!r}")
        return {"context": c["context"].model_dump(mode="json"),
                "ranges": c["ranges"].model_dump(mode="json") if c["ranges"] else None,
                "i5": c["i5"].model_dump(mode="json"),
                "i15_items": [i.model_dump(mode="json") for i in c["i15_items"]],
                "adjuster": c["adjuster"],
                "conditions": _conditions_json(c["conditions"])}

    return router
