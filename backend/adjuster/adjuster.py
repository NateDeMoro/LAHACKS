"""Context adjuster (B3): I4 in, I5 and I15 out. Use when an intake arrives and its danger limits
should be tightened, or when scoring the adjuster.

Code decides everything it can: structured rules (age, drug classes, pregnant flag) fire in code, values
come from models/rules.json. See rules.py. Intake never blocks on the LLM part."""
from dataclasses import dataclass
from datetime import datetime

from backend.adjuster import rules as R
from backend.contracts import (AdjustmentEvidence, ContextAdjustments, EvidenceItem, PatientContext)

STRUCTURED_ONLY = "structured only"


@dataclass
class Outcome:
    i5: ContextAdjustments
    i15: AdjustmentEvidence


def _build(ctx: PatientContext, structured: dict[str, str], text: list[tuple[str, str, str]],
           model: str, ts: datetime | None) -> Outcome:
    """text is (rule_id, fact, quote) already validated. Items and I5 follow rules.json order."""
    order = {r.id: i for i, r in enumerate(R.load_rules())}
    items = [EvidenceItem(rule_id=k, fact=v, quote=None) for k, v in structured.items()]
    items += [EvidenceItem(rule_id=r, fact=f, quote=q) for r, f, q in text]
    items.sort(key=lambda it: order[it.rule_id])
    i5 = R.merge(ctx.patient_id, [it.rule_id for it in items])
    i15 = AdjustmentEvidence(patient_id=ctx.patient_id, ts=ts or datetime.now().astimezone(), items=items,
                             quote_found=True if text else None, model=model)
    return Outcome(i5, i15)


def adjust_structured(ctx: PatientContext, ts: datetime | None = None) -> Outcome:
    """Structured rules only: instant, no LLM. Use when intake needs limits at once."""
    return _build(ctx, R.structured_facts(ctx), [], STRUCTURED_ONLY, ts)
