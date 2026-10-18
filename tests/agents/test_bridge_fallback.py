"""The backend functions that use the agents: a good reply is used as is, any failure runs the in-process code."""
from backend import agent_bridge, handlers
from backend.agent_bridge import AgentCallError, agent_fns
from backend.config import AgentsConfig
from backend.contracts import (AdjustmentEvidence, ConditionResolution, ContextAdjustments, DraftedRule, DraftPick,
                               PatientContext, ResolvedCondition, Source)

CFG = AgentsConfig(enabled=True)
CTX = PatientContext(patient_id="p1", age=60, sex="male", custom_conditions=["sepsis"])
FOUND = ResolvedCondition(typed="sepsis", canonical="Sepsis", code="A41.9", status="found")
RULE = DraftedRule(code="A41.9", canonical="Sepsis", picks=[DraftPick(vital="resp_rate", bound="high", menu_id="resp_rate_high_mild")],
                   sources=[Source(kind="pmid", id="1", title="T", year=2020, passage="p"),
                            Source(kind="pmid", id="2", title="U", year=2021, passage="q")])
ADJUST = handlers.AdjustReply(i5=ContextAdjustments(patient_id="p1", adjustments=[]),
                              i15=AdjustmentEvidence(patient_id="p1", items=[]), llm_ok=True)
SENTINEL = object()


def down(*a, **k):
    raise AgentCallError("no answer")


def test_adjust_uses_the_agent_reply():
    adjust, _ = agent_fns(None, CFG, call=lambda *a, **k: ADJUST.model_dump_json(), fallback_adjust=lambda c: SENTINEL)
    out = adjust(CTX)
    assert out.llm_ok and out.i5.patient_id == "p1"


def test_adjust_falls_back_when_the_agent_is_down_or_replies_garbage():
    for call in (down, lambda *a, **k: "not json"):
        adjust, _ = agent_fns(None, CFG, call=call, fallback_adjust=lambda c: SENTINEL)
        assert adjust(CTX) is SENTINEL


def test_conditions_apply_the_agent_drafts_through_the_normal_service():
    rep = handlers.ConditionsReply(resolution=ConditionResolution(patient_id="p1", items=[FOUND]),
                                   drafts={"A41.9": handlers.EvidenceReply(rule=RULE)})
    _, conditions = agent_fns(None, CFG, call=lambda *a, **k: rep.model_dump_json(),
                              fallback_conditions=lambda c: SENTINEL)
    out = conditions(CTX)
    assert [(a.vital, a.bound, a.tier) for a in out.adjustments] == [("resp_rate", "high", "warning")]
    assert out.evidence_items[0].unreviewed


def test_conditions_falls_back_when_the_agent_is_down():
    _, conditions = agent_fns(None, CFG, call=down, fallback_conditions=lambda c: SENTINEL)
    assert conditions(CTX) is SENTINEL


def test_a_missing_draft_reads_as_an_infra_error():
    rep = handlers.ConditionsReply(resolution=ConditionResolution(patient_id="p1", items=[FOUND]), drafts={})
    _, conditions = agent_fns(None, CFG, call=lambda *a, **k: rep.model_dump_json(), fallback_conditions=None)
    out = conditions(CTX)
    assert out.adjustments == [] and "no draft" in out.infra_errors[0]


def test_bridge_that_never_started_raises_instead_of_hanging():
    try:
        agent_bridge.AgentBridge(CFG).call("intake", "adjust", "{}", done_s=1)
    except AgentCallError as e:
        assert "not running" in str(e)
    else:
        raise AssertionError("expected AgentCallError")
