"""Rule firing from structured fields and the merge into I5. Use when deciding which rules apply from
age, drug classes and the pregnant flag, or turning fired rule ids into tightened danger limits.

Code decides every value: numbers come from models/rules.json, never from the LLM. A value is kept only if
it tightens the NEWS2 edge in ranges.DANGER (no edge today means any value tightens). When two rules move
the same edge the stricter one wins. Output is ordered by rules.json position so repeats are byte-identical."""
import json
from functools import lru_cache

from backend.adjuster.testset import RULES_PATH
from backend.contracts import Adjustment, ContextAdjustments, PatientContext, RulesFile, RuleSpec
from backend.risk_engine.ranges import DANGER

CLASS_RULES = {"beta_blocker": {"beta_blocker"}, "opioid": {"opioid"},
               "steroid_immunosuppressed": {"corticosteroid", "immunosuppressant"}}


@lru_cache
def load_rules() -> list[RuleSpec]:
    return RulesFile(**json.loads(RULES_PATH.read_text())).rules


def structured_facts(ctx: PatientContext) -> dict[str, str]:
    """Rules that fire from structured fields, with the fact naming the field. Keys are in rules.json order."""
    classes = set(ctx.drug_classes or [])
    out = {}
    for r in load_rules():
        if r.id == "age65" and ctx.age is not None and ctx.age >= 65:
            out[r.id] = f"age {ctx.age:g} is 65 or more"
        elif r.id == "pregnancy" and ctx.pregnant is True:
            out[r.id] = "pregnant flag is set"
        elif r.id in CLASS_RULES and (hit := sorted(classes & CLASS_RULES[r.id])):
            out[r.id] = f"drug_classes has {', '.join(hit)}"
    return out


def tightens(vital: str, bound: str, value: float) -> bool:
    low, high = DANGER[vital]
    edge = low if bound == "low" else high
    if edge is None:
        return True
    return value < edge if bound == "high" else value > edge


def merge(patient_id: str | None, fired: list[str], rules: list[RuleSpec] | None = None) -> ContextAdjustments:
    """I5 for the fired rule ids: tightening values only, stricter wins per (vital, bound), rules.json order."""
    best: dict[tuple[str, str], tuple[float, tuple[int, int], str]] = {}
    for i, r in enumerate(rules or load_rules()):
        if r.id not in fired:
            continue
        for j, a in enumerate(r.adjustments or []):
            if not tightens(a.vital, a.bound, a.value):
                continue
            key = (a.vital, a.bound)
            cur = best.get(key)
            if cur is None or (a.value < cur[0] if a.bound == "high" else a.value > cur[0]):
                best[key] = (a.value, (i, j), r.id)
    adj = [Adjustment(rule_id=rid, vital=v, bound=b, value=val)
           for (v, b), (val, _, rid) in sorted(best.items(), key=lambda kv: kv[1][1])]
    return ContextAdjustments(patient_id=patient_id, adjustments=adj)
