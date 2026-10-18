"""What each specialist agent does with a request. Plain async functions over JSON strings, so they run
without uagents; the blocking steps go to threads so one slow lookup never stalls the agent."""
import asyncio
from typing import Awaitable, Callable

from backend import handlers
from backend.contracts import PatientContext

AskDraft = Callable[[str, str], Awaitable[str]]  # (kind, payload) -> reply payload from the evidence agent


async def intake(kind: str, payload: str, ask_evidence: AskDraft) -> str:
    ctx = PatientContext.model_validate_json(payload)
    if kind == "adjust":
        return (await asyncio.to_thread(handlers.adjust, ctx)).model_dump_json()
    if kind == "conditions":
        resolution = await asyncio.to_thread(handlers.resolve_conditions, ctx)
        found = [i for i in resolution.items or [] if i.status == "found" and i.code]
        replies = await asyncio.gather(*(_draft(ask_evidence, i.code, i.canonical) for i in found))
        return handlers.ConditionsReply(resolution=resolution, drafts={i.code: r for i, r in zip(found, replies)}
                                        ).model_dump_json()
    raise ValueError(f"unknown intake request {kind!r}")


async def _draft(ask_evidence: AskDraft, code: str, canonical: str) -> handlers.EvidenceReply:
    """A failed or unreachable evidence agent reads as an infrastructure error, which the service already handles."""
    try:
        req = handlers.DraftRequest(code=code, canonical=canonical).model_dump_json()
        return handlers.EvidenceReply.model_validate_json(await ask_evidence("draft", req))
    except Exception as e:
        return handlers.EvidenceReply(infra_error=f"evidence agent: {e}")


async def evidence(kind: str, payload: str) -> str:
    if kind != "draft":
        raise ValueError(f"unknown evidence request {kind!r}")
    req = handlers.DraftRequest.model_validate_json(payload)
    return (await asyncio.to_thread(handlers.draft_rule, req.code, req.canonical)).model_dump_json()
