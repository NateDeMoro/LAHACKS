"""Citation gates for a drafted rule (pure functions). Use after the model has picked menu steps from
fetched abstracts: nothing it says moves a limit unless every gate passes in code.

Per claim (one model pick = one cited source): menu, pmid, passage, vital_named. Per menu id: sources
(enough distinct passing pmids). A recorded claim gate is True only if every claim for that menu id passed
it, so a failed draft shows everything that went wrong. A menu id survives on `sources` alone: a stray bad
claim next to enough good ones shows as a False gate but does not drop the pick."""
import re
from dataclasses import dataclass, field

from backend.adjuster.adjuster import norm
from backend.conditions.pubmed import Record
from backend.contracts import LimitMenu, MenuEntry

CLAIM_GATES = ("menu", "pmid", "passage", "vital_named")
ALL_GATES = (*CLAIM_GATES, "sources")

# A text match is a weak proxy for "this passage is about the vital"; it only has to be necessary.
LEXICON = {
    "hr": r"heart rates?|pulse|tachycardi\w*|bradycardi\w*|hr(?=\s*\d)",  # bare "hr" only before a number, so "24 hr" (hours) does not count
    "resp_rate": r"respiratory rates?|breathing|tachypne\w*|bradypne\w*",
    "spo2": r"oxygen saturation|spo2|spo\(2\)|hypox\w*",
    "temp_c": r"temperature|fever|febrile|hypotherm\w*|pyrexi\w*",
}
_PATTERNS = {v: re.compile(rf"\b(?:{p})\b", re.I) for v, p in LEXICON.items()}


@dataclass(frozen=True)
class Claim:
    vital: str
    bound: str
    menu_id: str
    pmid: str
    passage: str


@dataclass(frozen=True)
class Chosen:
    entry: MenuEntry
    claims: tuple[Claim, ...]  # passing claims, distinct pmids, in the model's order


@dataclass
class Selection:
    chosen: list[Chosen] = field(default_factory=list)  # menu order, one per (vital, bound)
    failed: dict[str, list[str]] = field(default_factory=dict)  # menu id -> failed gate names
    gates: dict[str, bool] = field(default_factory=dict)  # "<menu id>.<gate>" -> passed


def vital_named(passage: str, vital: str) -> bool:
    pat = _PATTERNS.get(vital)  # sbp has no lexicon: it can never be named
    return bool(pat and pat.search(passage))


def check_claim(claim: Claim, menu: LimitMenu, records: dict[str, Record], allowed_vitals: tuple[str, ...]
                ) -> dict[str, bool]:
    entry = next((e for e in menu.entries or [] if e.id == claim.menu_id), None)
    rec = records.get(claim.pmid)
    passage = norm(claim.passage)
    return {
        "menu": bool(entry and entry.vital == claim.vital and entry.bound == claim.bound
                     and claim.vital in allowed_vitals),
        "pmid": rec is not None,
        "passage": bool(rec and passage and passage in norm(rec.abstract)),
        "vital_named": vital_named(claim.passage, claim.vital),
    }


def _group(claims: list[Claim]) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = {}
    for c in claims:
        groups.setdefault(c.menu_id, []).append(c)
    return groups


def _passing(group: list[Claim], results: list[dict[str, bool]]) -> list[Claim]:
    seen, out = set(), []
    for c, r in zip(group, results):
        if all(r.values()) and c.pmid not in seen:
            seen.add(c.pmid)
            out.append(c)
    return out


def select(claims: list[Claim], menu: LimitMenu, records: dict[str, Record], allowed_vitals: tuple[str, ...],
           min_sources: int) -> Selection:
    """Run every gate. A menu id survives with >= min_sources distinct passing pmids. If several surviving
    ids share a (vital, bound), the milder wins: the one earliest in the menu's order."""
    sel, order = Selection(), {e.id: i for i, e in enumerate(menu.entries or [])}
    passed: dict[str, Chosen] = {}
    for menu_id, group in _group(claims).items():
        results = [check_claim(c, menu, records, allowed_vitals) for c in group]
        gate = {g: all(r[g] for r in results) for g in CLAIM_GATES}
        good = _passing(group, results)
        gate["sources"] = len(good) >= min_sources
        sel.gates.update({f"{menu_id}.{g}": ok for g, ok in gate.items()})
        if not gate["sources"]:
            sel.failed[menu_id] = [g for g in ALL_GATES if not gate[g]]
        else:
            entry = next(e for e in menu.entries if e.id == menu_id)
            passed[menu_id] = Chosen(entry, tuple(good))
    best: dict[tuple[str, str], Chosen] = {}
    for mid, ch in passed.items():
        key = (ch.entry.vital, ch.entry.bound)
        if key not in best or order[mid] < order[best[key].entry.id]:
            best[key] = ch
    sel.chosen = sorted(best.values(), key=lambda ch: order[ch.entry.id])
    return sel
