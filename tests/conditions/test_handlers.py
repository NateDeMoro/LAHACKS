"""The three entry points return contract models that survive a JSON round trip, so a caller in another process
can send and validate them. Network and model calls are stubbed."""
from backend import handlers
from backend.adjuster import adjuster as A
from backend.conditions import evidence, lookup
from backend.contracts import DraftedRule, DraftPick, PatientContext, ResolvedCondition, Source


def roundtrip(reply):
    return type(reply).model_validate_json(reply.model_dump_json())


def test_adjust_reply_keeps_the_outcome_fields(monkeypatch):
    ctx = PatientContext(patient_id="p1", age=50, sex="male")
    out = A.adjust_structured(ctx)
    monkeypatch.setattr(A, "adjust", lambda c: out)
    reply = roundtrip(handlers.adjust(ctx))
    assert reply.i5 == out.i5 and reply.i15 == out.i15 and reply.llm_ok == out.llm_ok


def test_resolve_conditions_wraps_items_in_i16(monkeypatch):
    item = ResolvedCondition(typed="sepsis", canonical="Sepsis", code="A41.9", status="found")
    monkeypatch.setattr(lookup, "resolve", lambda terms, normalize_fn=None: [item])
    ctx = PatientContext(patient_id="p1", custom_conditions=["sepsis"])
    res = roundtrip(handlers.resolve_conditions(ctx))
    assert res.patient_id == "p1" and res.items == [item] and res.ts is not None


def test_draft_rule_reply_carries_the_rule_or_the_reason(monkeypatch):
    rule = DraftedRule(code="A41.9", canonical="Sepsis", picks=[DraftPick(vital="hr", bound="high", menu_id="hr_high_mild")],
                       sources=[Source(kind="pmid", id="1", title="T", year=2020, passage="p")])
    monkeypatch.setattr(evidence, "draft", lambda code, name, **kw: evidence.DraftOutcome(rule))
    assert roundtrip(handlers.draft_rule("A41.9", "Sepsis")).rule == rule
    monkeypatch.setattr(evidence, "draft", lambda code, name, **kw: evidence.DraftOutcome(
        abstained=True, failed={"hr_high_mild": ["names_vital"]}, infra_error="pubmed down"))
    reply = roundtrip(handlers.draft_rule("A41.9", "Sepsis"))
    assert reply.rule is None and reply.abstained and reply.failed == {"hr_high_mild": ["names_vital"]}
    assert reply.infra_error == "pubmed down"
