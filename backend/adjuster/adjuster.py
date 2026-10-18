"""Context adjuster (B3): I4 in, I5 and I15 out. Use when an intake arrives and its danger limits
should be tightened, or when scoring the adjuster.

Code decides everything it can: structured rules (age, drug classes, pregnant flag) fire in code, values
come from models/rules.json. See rules.py. Intake never blocks on the LLM part."""
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.adjuster import prompt as P
from backend.adjuster import rules as R
from backend.config import CONFIG, AdjusterConfig, LlmConfig
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


_LOCK = threading.Lock()


def _cache_get(path, key) -> list[TextProposal] | None:
    try:
        return [TextProposal(**p) for p in json.loads(path.read_text())[key]]
    except Exception:  # missing, corrupted or schema-stale entry: a miss, never an error
        return None


def _cache_key(msgs, cfg: LlmConfig) -> str:
    """Hash of everything that changes the reply: messages, prompt version, model settings, reply schema."""
    parts = [msgs, P.PROMPT_VERSION, cfg.model, cfg.temperature, cfg.max_tokens, cfg.reasoning_effort,
             TextReply.model_json_schema()]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _cache_put(path, key, kept: list[TextProposal]):
    with _LOCK:
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[key] = [p.model_dump() for p in kept]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, path)
        except OSError:  # a failed cache write must not stop intake
            pass


def _log(path, i15: AdjustmentEvidence):
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(i15.model_dump_json() + "\n")
        except OSError:  # a failed log append must not stop intake
            pass


def adjust(ctx: PatientContext, *, client=None, cfg: LlmConfig | None = None, llm: bool = True,
           ts: datetime | None = None, adj: AdjusterConfig | None = None,
           use_cache: bool | None = None, write_log: bool | None = None) -> Outcome:
    """Full result: structured rules plus one LLM call for facts only the complaint holds. If the call fails,
    the structured result is returned (intake never blocks on the LLM) and nothing is cached. Only validated
    text proposals are cached, keyed on the exact messages, prompt version, model settings and reply schema; structured rules are always recomputed.
    A bad cache entry counts as a miss and cache or log write failures are ignored. The "structured only" model
    marker is used when the LLM call failed or was skipped (empty chief complaint).
    Appends I15 to the evaluation log unless write_log is off (scoring turns both off)."""
    cfg, adj = cfg or CONFIG.llm, adj or CONFIG.adjuster
    use_cache = adj.use_cache if use_cache is None else use_cache
    write_log = adj.write_log if write_log is None else write_log
    structured = R.structured_facts(ctx)
    out = None
    if llm and (ctx.chief_complaint or "").strip():
        msgs = P.messages(ctx)
        key = _cache_key(msgs, cfg)
        kept = _cache_get(adj.cache_path, key) if use_cache else None
        dropped, latency = [], 0.0
        if kept is None:
            try:
                res = json_completion(msgs, TextReply, cfg, client)
                kept, dropped = validate(res.value.proposals, ctx, structured)
                latency = res.latency_s
                if use_cache:
                    _cache_put(adj.cache_path, key, kept)
            except LlmError:
                pass
        if kept is not None:
            out = _build(ctx, structured, [(p.rule_id, p.fact, p.quote) for p in kept],
                         f"{cfg.model} {P.PROMPT_VERSION}", ts)
            out.dropped, out.latency_s, out.llm_ok = dropped, latency, True
    if out is None:
        out = _build(ctx, structured, [], STRUCTURED_ONLY, ts)
    if write_log:
        _log(adj.log_path, out.i15)
    return out
