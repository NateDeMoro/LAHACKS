"""Specialist-agent dispatch with the lookup and evidence steps stubbed: the fan-out to the evidence agent,
and what happens when it fails."""
import asyncio

import pytest

from agent import dispatch
from backend import handlers
from backend.contracts import (ConditionResolution, DraftedRule, DraftPick, PatientContext, ResolvedCondition,
                               Source)

CTX = PatientContext(patient_id="p1", age=60, sex="male", custom_conditions=["sepsis", "blorptic"])
FOUND = ResolvedCondition(typed="sepsis", canonical="Sepsis", code="A41.9", status="found")
MISSING = ResolvedCondition(typed="blorptic", status="not_found")
RULE = DraftedRule(code="A41.9", canonical="Sepsis", picks=[DraftPick(vital="hr", bound="high", menu_id="hr_high_mild")],
                   sources=[Source(kind="pmid", id="1", title="T", year=2020, passage="p")])


@pytest.fixture
def stub_lookup(monkeypatch):
    monkeypatch.setattr(handlers, "resolve_conditions",
                        lambda ctx: ConditionResolution(patient_id=ctx.patient_id, items=[FOUND, MISSING]))


def run(coro):
    return asyncio.run(coro)


def test_conditions_asks_the_evidence_agent_only_for_found_codes(stub_lookup):
    asked = []

    async def ask(kind, payload):
        asked.append((kind, handlers.DraftRequest.model_validate_json(payload)))
        return handlers.EvidenceReply(rule=RULE).model_dump_json()

    out = handlers.ConditionsReply.model_validate_json(run(dispatch.intake("conditions", CTX.model_dump_json(), ask)))
    assert asked == [("draft", handlers.DraftRequest(code="A41.9", canonical="Sepsis"))]
    assert out.drafts["A41.9"].rule == RULE and out.resolution.items == [FOUND, MISSING]


def test_an_unreachable_evidence_agent_becomes_an_infra_error_not_a_crash(stub_lookup):
    async def ask(kind, payload):
        raise ConnectionError("no answer")

    out = handlers.ConditionsReply.model_validate_json(run(dispatch.intake("conditions", CTX.model_dump_json(), ask)))
    assert out.drafts["A41.9"].rule is None and "no answer" in out.drafts["A41.9"].infra_error


def test_evidence_agent_serves_draft_and_rejects_other_kinds(monkeypatch):
    monkeypatch.setattr(handlers, "draft_rule", lambda code, name: handlers.EvidenceReply(rule=RULE))
    req = handlers.DraftRequest(code="A41.9", canonical="Sepsis").model_dump_json()
    assert handlers.EvidenceReply.model_validate_json(run(dispatch.evidence("draft", req))).rule == RULE
    with pytest.raises(ValueError):
        run(dispatch.evidence("adjust", req))
    with pytest.raises(ValueError):
        run(dispatch.intake("draft", CTX.model_dump_json(), None))
