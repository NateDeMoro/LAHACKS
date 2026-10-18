"""Tools the coordinator's LLM can call against the local backend: read the board, start an intake from chat
and read back its card. Use when changing what the agent can see or do."""
import asyncio
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


VITALS = ("hr", "resp_rate", "spo2", "temp_c")


async def _post(path: str, body: dict):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(BACKEND + path, json=body)
        r.raise_for_status()
        return r.json()


async def _free_wearable() -> int | None:
    """A free chat bed (ids from 200) first, so the strap and the scenario beds stay as they are; else any free one."""
    free = [w["wearable_id"] for w in await _get("/intake/wearables") if not w.get("patient_id")]
    return min(free, key=lambda w: (w < 200, w)) if free else None


async def submit_intake(age: float, sex: str, conditions: list[str] | None = None, chief_complaint: str | None = None,
                        medications: list[str] | None = None, name: str | None = None) -> dict:
    """Start an intake for a new waiting patient. Conditions are typed names, looked up and checked in the background."""
    wearable = await _free_wearable()
    if wearable is None:
        return {"error": "no free wearable"}
    rec = {"wearable_id": wearable, "age": age, "sex": sex, "name": name, "chief_complaint": chief_complaint,
           "medications": medications or None, "custom_conditions": conditions or None}
    done = await _post("/intake", {k: v for k, v in rec.items() if v is not None})
    return {"patient_id": done["patient_id"], "wearable_id": wearable,
            "note": "Intake started. Conditions are checked in the background; call check_intake."}


def summarize_card(card: dict) -> dict:
    """The parts of an intake card a nurse cares about: what was understood, what changed, why, and the limits."""
    cond = card.get("conditions")
    items = card.get("i15_items") or []
    out = {"adjuster": card.get("adjuster"), "conditions_state": cond["state"] if cond else None,
           "conditions": [{k: i.get(k) for k in ("typed", "status", "canonical", "code", "checklist")}
                          for i in (cond["resolution"]["items"] if cond and cond.get("resolution") else [])],
           "not_applied": (cond or {}).get("suggestions") or [], "problems": (cond or {}).get("infra_errors") or [],
           "table_rules": [{"rule": i["rule_id"], "fact": i.get("fact"), "quote": i.get("quote")}
                           for i in items if not i.get("unreviewed")],
           "drafted_limits_unreviewed": [{"rule": i["rule_id"], "fact": i.get("fact"),
                                          "sources": [{"pmid": s.get("id"), "title": s.get("title"), "year": s.get("year")}
                                                      for s in i.get("sources") or []]}
                                         for i in items if i.get("unreviewed")]}
    rng = card.get("ranges") or {}
    out["limits"] = {v: {k: rng[v].get(k) for k in ("safe_low", "safe_high", "danger_low", "danger_high")}
                     for v in VITALS if isinstance(rng.get(v), dict)}
    return out


def _ready(card: dict) -> bool:
    cond = card.get("conditions")
    return card.get("adjuster") != "pending" and (cond is None or cond["state"] != "pending")


async def check_intake(patient_id: str, wait_s: float = 30) -> dict:
    """The intake card, waiting up to wait_s seconds for the background checks to finish."""
    loop = asyncio.get_running_loop()
    end = loop.time() + min(max(wait_s, 0), 60)
    while True:
        card = await _get(f"/intake/{patient_id}")
        if _ready(card) or loop.time() >= end:
            return {"patient_id": patient_id, "finished": _ready(card), **summarize_card(card)}
        await asyncio.sleep(3)


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

TOOL_SPECS += [
    {"type": "function", "function": {
        "name": "submit_intake",
        "description": ("Add a new waiting patient. Needs age and sex from the nurse; do not guess them. Put only diagnoses or "
                        "medical conditions the nurse names in `conditions`, as typed; symptoms go in chief_complaint. Returns a patient_id; then call check_intake."),
        "parameters": {"type": "object", "properties": {
            "age": {"type": "number"}, "sex": {"type": "string", "enum": ["male", "female"]},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "chief_complaint": {"type": "string"}, "medications": {"type": "array", "items": {"type": "string"}},
            "name": {"type": "string"}}, "required": ["age", "sex"]}}},
    {"type": "function", "function": {
        "name": "check_intake",
        "description": ("Read back what the system did with an intake: which typed conditions are real, which limits "
                        "changed and why, with sources. Waits up to 30 s for the background checks; if `finished` is "
                        "false, say it is still running and offer to check again."),
        "parameters": {"type": "object", "properties": {"patient_id": {"type": "string"}}, "required": ["patient_id"]}}},
]

HANDLERS = {"list_patients": list_patients, "patient_status": patient_status,
            "submit_intake": submit_intake, "check_intake": check_intake}
