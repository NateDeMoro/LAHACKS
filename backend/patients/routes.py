"""HTTP side of the patient registry: the board's list, calling a patient in, and the vitals history."""
from typing import Callable

from fastapi import APIRouter, HTTPException

from backend.patients.registry import PatientRegistry


def build_router(registry: PatientRegistry, open_alerts: Callable[[str], list[dict]],
                 call_in: Callable[[str], None]) -> APIRouter:
    router = APIRouter(prefix="/patients")

    def _row(row):
        return {**row.model_dump(mode="json"), "alerts": open_alerts(row.patient_id)}

    @router.get("")
    async def patients():
        return [_row(r) for r in registry.rows()]

    @router.post("/{patient_id}/called-in")
    async def called_in(patient_id: str):
        if registry.get(patient_id) is None:
            raise HTTPException(404, f"unknown patient {patient_id!r}")
        call_in(patient_id)
        return _row(registry.get(patient_id))

    @router.get("/{patient_id}/history")
    async def history(patient_id: str):
        if registry.get(patient_id) is None:
            raise HTTPException(404, f"unknown patient {patient_id!r}")
        return [r.model_dump(mode="json") for r in registry.history(patient_id)]

    return router
