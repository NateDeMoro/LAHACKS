"""Entry points for the LLM-backed steps: adjust, resolve typed conditions, draft a rule. Each takes plain data
and returns a contract model, so a caller in another process (a Fetch.ai agent) can send the JSON form
(`model_dump_json`) and validate the reply with the same model. The conditions package is imported inside the
functions so the intake service loads without it."""
from backend.adjuster import adjuster as A
from backend.contracts import (AdjustmentEvidence, ConditionResolution, ContextAdjustments, DraftedRule, Model,
                               PatientContext)
from backend.timeutil import now_la


class AdjustReply(Model):
    i5: ContextAdjustments | None = None
    i15: AdjustmentEvidence | None = None
    llm_ok: bool | None = None  # false when the model call failed and only table rules applied
    latency_s: float | None = None


class EvidenceReply(Model):
    """A drafted rule (I17), or why there is none. Mirrors conditions.evidence.DraftOutcome."""
    rule: DraftedRule | None = None
    abstained: bool = False
    failed: dict[str, list[str]] | None = None  # gate failures by menu id
    infra_error: str | None = None  # PubMed or model failure: nothing stored, try again later
    from_store: bool = False
    disabled: bool = False  # kill switch


class DraftRequest(Model):
    code: str
    canonical: str


class ConditionsReply(Model):
    """Everything the condition step needs from the agents in one reply: the lookup, and a draft per found code."""
    resolution: ConditionResolution
    drafts: dict[str, EvidenceReply]


def adjust(ctx: PatientContext) -> AdjustReply:
    out = A.adjust(ctx)
    return AdjustReply(i5=out.i5, i15=out.i15, llm_ok=out.llm_ok, latency_s=out.latency_s)


def resolve_conditions(ctx: PatientContext) -> ConditionResolution:
    """Look up each typed condition (raises if the lookup itself fails; the caller marks those unavailable)."""
    from backend.conditions import lookup, normalize
    terms = ctx.custom_conditions or []
    norm = normalize.for_config()
    return ConditionResolution(patient_id=ctx.patient_id, ts=now_la(), items=lookup.resolve(terms, normalize_fn=norm))


def draft_rule(code: str, canonical: str) -> EvidenceReply:
    from backend.conditions import evidence
    out = evidence.draft(code, canonical, vocabulary="nlm_conditions")
    return EvidenceReply(rule=out.rule, abstained=out.abstained, failed=out.failed or None,
                         infra_error=out.infra_error, from_store=out.from_store, disabled=out.disabled)
