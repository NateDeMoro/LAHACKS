"""Read-only tools the agent's LLM can call against the local backend. Use when changing what the agent can see."""
import os

import httpx

BACKEND = os.getenv("AGENT_BACKEND_URL", "http://localhost:8000").rstrip("/")


async def _get(path: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(BACKEND + path)
        r.raise_for_status()
        return r.json()


async def list_patients() -> list[dict]:
    """Waiting patients with their open alerts. Skips called-in patients and alerts that a newer alert superseded."""
    out = []
    for p in await _get("/patients"):
        if p.get("called_in_ts"):
            continue
        alerts = p.get("alerts") or []
        superseded = {a for al in alerts for a in (al.get("supersedes") or [])}
        live = [a for a in alerts if a.get("alert_id") not in superseded]
        out.append({
            "patient_id": p["patient_id"], "name": p.get("name"), "bed": p.get("bed"),
            "arrival_ts": p.get("arrival_ts"),
            "open_alerts": [{k: a.get(k) for k in ("severity", "trigger", "vital", "ts", "message")} for a in live],
        })
    return out


async def patient_status(patient_id: str) -> dict:
    """Latest risk result (last history item) for one patient."""
    history = await _get(f"/patients/{patient_id}/history")
    if not history:
        return {"patient_id": patient_id, "latest": None}
    r = history[-1]
    keep = ("ts", "level", "vital", "reason", "news2", "vital_levels", "vital_values", "trend_tier", "trend_reason_fast")
    return {"patient_id": patient_id, "latest": {k: r.get(k) for k in keep}}


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_patients",
        "description": "List patients still waiting, each with open (not superseded) alerts. Patients already called in are excluded.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "patient_status",
        "description": "Latest risk result for one patient: level, NEWS2 score, per-vital levels and values, trend tier.",
        "parameters": {"type": "object", "properties": {"patient_id": {"type": "string"}},
                       "required": ["patient_id"]}}},
]

HANDLERS = {"list_patients": list_patients, "patient_status": patient_status}
