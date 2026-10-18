"""What the context-adjuster LLM returns, and its split into I5 and I15.
Use when asking the model for threshold tightenings or turning its reply into interface objects.

Stricter than the exported I5/I15 schemas (no nulls, required fields, enums) because structured-output
modes handle nullable-everywhere schemas badly. Each adjustment carries its own fact and quote so the
rule, its number and its evidence travel together. Code, not the LLM, fills timestamp, model name and
the quote-found flag."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.contracts import (Adjustment, AdjustmentEvidence, Bound, ContextAdjustments,
                               EvidenceItem, Vital)

PROMPT_VERSION = "b1-0"


class ProposedAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    vital: Vital
    bound: Bound
    value: float  # new danger threshold in the vital's units
    fact: str     # what the model found in the intake
    quote: str    # exact words from the chief complaint that support it


class AdjusterProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adjustments: list[ProposedAdjustment]  # empty when nothing in the intake matches a rule


def to_i5(patient_id: str, p: AdjusterProposal) -> ContextAdjustments:
    return ContextAdjustments(patient_id=patient_id, adjustments=[
        Adjustment(rule_id=a.rule_id, vital=a.vital, bound=a.bound, value=a.value) for a in p.adjustments])


def to_i15(patient_id: str, p: AdjusterProposal, model: str, ts: datetime) -> AdjustmentEvidence:
    """quote_found stays null here; the word-for-word check against the complaint belongs to B3."""
    return AdjustmentEvidence(
        patient_id=patient_id, ts=ts, quote_found=None, model=f"{model} {PROMPT_VERSION}",
        items=[EvidenceItem(rule_id=a.rule_id, fact=a.fact, quote=a.quote) for a in p.adjustments])
