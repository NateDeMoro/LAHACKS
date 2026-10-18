"""Context adjuster (B3): I4 in, I5 and I15 out. Use when an intake arrives and its danger limits
should be tightened, or when scoring the adjuster.

Code decides everything it can: structured rules (age, drug classes, pregnant flag) fire in code, values
come from models/rules.json. See rules.py. Intake never blocks on the LLM part."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.adjuster import prompt as P
from backend.adjuster import rules as R
from backend.config import CONFIG, LlmConfig
from backend.contracts import (AdjustmentEvidence, ContextAdjustments, EvidenceItem, PatientContext)
from backend.llm import LlmError, json_completion

STRUCTURED_ONLY = "structured only"
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u201c": '"',
                         "\u201d": '"', "\u201e": '"'})
TextRule = Literal["chemo_fever", "suspected_infection", "opioid", "steroid_immunosuppressed",
                   "beta_blocker", "pregnancy"]


class TextProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: TextRule
    fact: str   # what the model found in the complaint
    quote: str  # exact words from the chief complaint


class TextReply(BaseModel):
    """What the LLM returns: facts and quotes only, no vital, bound or value. Strict (no nulls) for structured output."""
    model_config = ConfigDict(extra="forbid")
    proposals: list[TextProposal]  # empty when nothing in the complaint matches a rule


@dataclass
class Outcome:
    i5: ContextAdjustments
    i15: AdjustmentEvidence
    dropped: list[str] = field(default_factory=list)  # validator drops, "rule_id: reason"; not part of I15
    latency_s: float = 0.0  # 0 on a cache hit or when the LLM was not called
    llm_ok: bool = False


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


def norm(s: str) -> str:
    """Lowercase, straighten curly quotes, collapse whitespace: the only leniency in the quote check."""
    return re.sub(r"\s+", " ", s.translate(_QUOTES).lower()).strip()


def validate(proposals: list[TextProposal], ctx: PatientContext, structured: dict[str, str]
             ) -> tuple[list[TextProposal], list[str]]:
    """Keep proposals that pass; return (kept, drop reasons). One proposal per rule (first wins)."""
    kept, dropped, complaint = [], [], norm(ctx.chief_complaint or "")
    for p in proposals:
        if p.rule_id not in P.TEXT_RULES:
            dropped.append(f"{p.rule_id}: not a text rule")
        elif p.rule_id in structured:
            dropped.append(f"{p.rule_id}: structured already fired")
        elif p.rule_id == "pregnancy" and ctx.pregnant is not None:
            dropped.append("pregnancy: pregnant flag is not null")
        elif not p.quote.strip() or norm(p.quote) not in complaint:
            dropped.append(f"{p.rule_id}: quote not in complaint")
        elif any(k.rule_id == p.rule_id for k in kept):
            dropped.append(f"{p.rule_id}: duplicate")
        else:
            kept.append(p)
    return kept, dropped


def adjust(ctx: PatientContext, *, client=None, cfg: LlmConfig | None = None, llm: bool = True,
           ts: datetime | None = None) -> Outcome:
    """Full result: structured rules plus one LLM call for facts only the complaint holds. If the call fails,
    the structured result is returned (intake never blocks on the LLM)."""
    cfg = cfg or CONFIG.llm
    structured = R.structured_facts(ctx)
    if not llm or not (ctx.chief_complaint or "").strip():
        return _build(ctx, structured, [], STRUCTURED_ONLY, ts)
    try:
        res = json_completion(P.messages(ctx), TextReply, cfg, client)
    except LlmError:
        return _build(ctx, structured, [], STRUCTURED_ONLY, ts)
    kept, dropped = validate(res.value.proposals, ctx, structured)
    out = _build(ctx, structured, [(p.rule_id, p.fact, p.quote) for p in kept],
                 f"{cfg.model} {P.PROMPT_VERSION}", ts)
    out.dropped, out.latency_s, out.llm_ok = dropped, res.latency_s, True
    return out
