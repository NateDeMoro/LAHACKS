from types import SimpleNamespace

from backend.conditions import menu as M
from backend.conditions import service as S
from backend.config import ConditionsConfig
from backend.contracts import (Candidate, DraftedRule, DraftPick, PatientContext, ResolvedCondition, Source)
from backend.risk_engine import ranges

CTX = PatientContext(patient_id="p1", age=50, sex="male", height_cm=175, weight_kg=80,
                     custom_conditions=["sickle cell disease"])
SRC = [Source(kind="pmid", id="1", title="T1", year=2020, passage="heart rate rose"),
       Source(kind="pmid", id="2", title="T2", year=2021, passage="tachycardia was common")]


def found(code="D57", name="Sickle cell disease"):
    return ResolvedCondition(typed="sickle cell disease", canonical=name, vocabulary="nlm_conditions", code=code,
                             status="found")


def rule(*menu_ids, code="D57"):
    by_id = {e.id: e for e in M.load_menu().entries}
    picks = [DraftPick(vital=by_id[i].vital, bound=by_id[i].bound, menu_id=i) for i in menu_ids]
    return DraftedRule(vocabulary="nlm_conditions", code=code, canonical="Sickle cell disease", picks=picks,
                       sources=SRC, evidence_label="medium", evidence_hash="h", gates={"passage_in_abstract": True})


def outcome(r=None, infra=None):
    return SimpleNamespace(rule=r, abstained=r is None and infra is None, failed={}, infra_error=infra, from_store=False)


def run(resolved, draft, ctx=CTX, cfg=ConditionsConfig()):
    calls = []

    def draft_fn(code, canonical):
        calls.append(code)
        return draft(code) if callable(draft) else draft
    out = S.process(ctx, resolve_fn=lambda terms: resolved, draft_fn=draft_fn, cfg=cfg)
    return out, calls


def test_no_custom_conditions_means_nothing_to_do():
    assert S.process(CTX.model_copy(update={"custom_conditions": None}), resolve_fn=None, draft_fn=None) is None
    assert S.process(CTX.model_copy(update={"custom_conditions": []}), resolve_fn=None, draft_fn=None) is None


def test_found_condition_with_a_pick_becomes_a_warning_tier_adjustment_from_the_menu():
    out, calls = run([found()], outcome(rule("hr_high_mild")))
    band = ranges.build_population_ranges(CTX).hr
    (adj,) = out.adjustments
    assert (adj.rule_id, adj.vital, adj.bound, adj.tier) == ("draft:D57", "hr", "high", "warning")
    assert adj.value == band.safe_high - 5  # the number came from the menu step, not from the model
    assert calls == ["D57"]
    (item,) = out.evidence_items
    assert item.rule_id == "draft:D57" and item.unreviewed is True and item.sources == SRC and item.quote is None
    assert out.resolution.items[0].status == "found" and out.resolution.patient_id == "p1"


def test_checklist_match_sets_the_flag_and_never_drafts():
    item = ResolvedCondition(typed="high blood pressure", status="checklist", checklist="hypertension")
    out, calls = run([item], outcome(rule("hr_high_mild")))
    assert out.checklist_flags == ["hypertension"] and out.adjustments == [] and calls == []


def test_ambiguous_not_found_and_unavailable_apply_nothing():
    amb = ResolvedCondition(typed="diabetes", status="ambiguous",
                            candidates=[Candidate(canonical="A", code="E10"), Candidate(canonical="B", code="E11")])
    for item in (amb, ResolvedCondition(typed="x", status="not_found"), ResolvedCondition(typed="x", status="unavailable")):
        out, calls = run([item], outcome(rule("hr_high_mild")))
        assert out.adjustments == [] and calls == [] and out.resolution.items[0].status == item.status


def test_kill_switch_stops_drafting_but_keeps_the_lookup_result():
    out, calls = run([found()], outcome(rule("hr_high_mild")), cfg=ConditionsConfig(enabled=False))
    assert calls == [] and out.adjustments == [] and out.resolution.items[0].status == "found"


def test_abstention_applies_nothing():
    out, _ = run([found()], outcome(None))
    assert out.adjustments == [] and out.evidence_items == []


def test_a_pick_that_cannot_tighten_the_patients_band_is_skipped_and_reported():
    from backend.contracts import LimitMenu, MenuEntry
    dead = MenuEntry(id="t378", vital="temp_c", bound="high", kind="absolute", amount=37.8, label="x", source="s")
    menu = LimitMenu(version=1, entries=[dead])
    band = ranges.build_population_ranges(CTX).temp_c
    assert M.target_edge(dead, band.safe_low, band.safe_high) is None, band  # the fitted ceiling (37.3) is already below 37.8
    draft = SimpleNamespace(rule=DraftedRule(code="D57", canonical="X", picks=[DraftPick(vital="temp_c", bound="high", menu_id="t378")],
                                             sources=SRC), abstained=False, failed={}, infra_error=None, from_store=False)
    out = S.process(CTX, resolve_fn=lambda t: [found()], draft_fn=lambda c, n: draft, menu=menu)
    assert out.adjustments == [] and out.evidence_items == []
    assert out.suggestions == [{"code": "D57", "menu_id": "t378", "reason": "no effect on this band"}]


def test_two_conditions_on_one_vital_keep_the_milder_step():
    two = CTX.model_copy(update={"custom_conditions": ["a", "b"]})
    resolved = [found("D57"), found("J45")]
    out, _ = run(resolved, lambda code: outcome(rule("hr_high_strong" if code == "D57" else "hr_high_mild", code=code)),
                 ctx=two)
    band = ranges.build_population_ranges(two).hr
    (adj,) = out.adjustments
    assert adj.value == band.safe_high - 5 and adj.rule_id == "draft:J45"


def test_vital_outside_the_allowed_list_is_ignored():
    out, _ = run([found()], outcome(rule("hr_high_mild")), cfg=ConditionsConfig(allowed_vitals=("temp_c",)))
    assert out.adjustments == []


def test_infrastructure_failure_is_reported_and_never_raises():
    out, _ = run([found()], outcome(None, infra="PubMed down"))
    assert out.adjustments == [] and out.infra_errors == ["D57: PubMed down"]


def test_resolver_failure_marks_every_term_unavailable():
    def boom(terms):
        raise RuntimeError("network")
    out = S.process(CTX, resolve_fn=boom, draft_fn=lambda c, n: None)
    assert [i.status for i in out.resolution.items] == ["unavailable"]


def test_resolution_timestamp_is_timezone_aware():
    out, _ = run([found()], outcome(None))
    assert out.resolution.ts.tzinfo is not None
