"""Custom-condition processing for one intake: resolve typed terms, draft limits for real conditions with no
table rule, and turn each pick into a warning-tier adjustment. Pure orchestration: the lookup and the evidence
step are injected, so this never touches the network itself. The model never supplies a number: code takes it
from the limit menu and the patient's own safe band."""
from dataclasses import dataclass, field

from backend.conditions import menu as M
from backend.config import CONFIG, ConditionsConfig
from backend.contracts import (Adjustment, ConditionResolution, EvidenceItem, PatientContext, ResolvedCondition)
from backend.risk_engine import ranges
from backend.timeutil import now_la


@dataclass
class ConditionOutcome:
    resolution: ConditionResolution
    checklist_flags: list[str] = field(default_factory=list)
    adjustments: list = field(default_factory=list)  # warning-tier Adjustments, one per vital and bound
    evidence_items: list = field(default_factory=list)  # I15 items for the drafted rules that applied
    suggestions: list = field(default_factory=list)  # picks that did not apply, with the reason
    infra_errors: list = field(default_factory=list)


def _resolve(ctx: PatientContext, resolve_fn) -> list[ResolvedCondition]:
    terms = ctx.custom_conditions or []
    try:
        return resolve_fn(terms)
    except Exception:  # a lookup failure must read as "unavailable", never as "not found"
        return [ResolvedCondition(typed=t, status="unavailable") for t in terms]


def _adjustment(code: str, pick, entry, band) -> Adjustment | None:
    edge = M.target_edge(entry, band.safe_low, band.safe_high)
    if edge is None:
        return None
    return Adjustment(rule_id=f"draft:{code}", vital=pick.vital, bound=pick.bound, value=edge, tier="warning")


def _milder(a: Adjustment, b: Adjustment) -> Adjustment:
    """Same vital and bound: keep the step that tightens less, so a pile of conditions cannot stack alert noise."""
    return max(a, b, key=lambda x: x.value) if a.bound == "high" else min(a, b, key=lambda x: x.value)


def process(ctx: PatientContext, *, resolve_fn, draft_fn, menu=None, cfg: ConditionsConfig = CONFIG.conditions
            ) -> ConditionOutcome | None:
    """None when the intake has no custom conditions. draft_fn(code, canonical) returns an evidence DraftOutcome."""
    if not ctx.custom_conditions:
        return None
    items = _resolve(ctx, resolve_fn)
    out = ConditionOutcome(resolution=ConditionResolution(patient_id=ctx.patient_id, ts=now_la(), items=items))
    out.checklist_flags = [i.checklist for i in items if i.status == "checklist" and i.checklist]
    if not cfg.enabled:
        return out
    menu = menu or M.load_menu(cfg.menu_path)
    by_id = {e.id: e for e in menu.entries}
    flagged = ctx.model_copy(update={"conditions": sorted({*(ctx.conditions or []), *out.checklist_flags})})
    pop = ranges.build_population_ranges(flagged)
    chosen: dict[tuple[str, str], Adjustment] = {}
    for item in (i for i in items if i.status == "found" and i.code):
        draft = draft_fn(item.code, item.canonical)
        if draft.infra_error:
            out.infra_errors.append(f"{item.code}: {draft.infra_error}")
            continue
        if draft.rule is None:
            continue
        for pick in draft.rule.picks or []:
            entry = by_id.get(pick.menu_id)
            if entry is None or pick.vital not in cfg.allowed_vitals:
                out.suggestions.append({"code": item.code, "menu_id": pick.menu_id, "reason": "not allowed"})
                continue
            adj = _adjustment(item.code, pick, entry, getattr(pop, pick.vital))
            if adj is None:
                out.suggestions.append({"code": item.code, "menu_id": pick.menu_id, "reason": "no effect on this band"})
                continue
            key = (adj.vital, adj.bound)
            chosen[key] = _milder(chosen[key], adj) if key in chosen else adj
        out.evidence_items.append(EvidenceItem(
            rule_id=f"draft:{item.code}", unreviewed=True, sources=draft.rule.sources,
            fact=f"{item.canonical}: " + ", ".join(f"{p.vital} {p.bound} ({p.menu_id})" for p in draft.rule.picks or [])))
    out.adjustments = list(chosen.values())
    kept = {a.rule_id for a in out.adjustments}
    out.evidence_items = [e for e in out.evidence_items if e.rule_id in kept]
    return out
