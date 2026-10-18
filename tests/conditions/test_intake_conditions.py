"""Custom conditions through the intake service with a real RiskEngine and stubbed lookup/evidence/adjuster.
Pins the reviewer's findings: the draft must survive the adjuster landing later and a resubmit."""
import asyncio
import threading
from types import SimpleNamespace

from backend.adjuster import adjuster as A
from backend.conditions import service as S
from backend.config import CONFIG
from backend.contracts import DraftedRule, DraftPick, IntakeRecord, ResolvedCondition, Source
from backend.intake.service import IntakeService
from backend.risk_engine.engine import RiskEngine

SRC = [Source(kind="pmid", id="1", title="T1", year=2020, passage="heart rate rose"),
       Source(kind="pmid", id="2", title="T2", year=2021, passage="tachycardia was common")]
WEARABLE = CONFIG.receiver.wearable_id


def rec(*terms, pid="p1", cc="cough"):
    return IntakeRecord(patient_id=pid, wearable_id=WEARABLE, age=50, sex="male", height_cm=175, weight_kg=80,
                        custom_conditions=list(terms) or None, chief_complaint=cc)


class World:
    """Stubs with gates so a test decides which slow part finishes first."""

    def __init__(self, status="found", menu_id="hr_high_mild", checklist=None):
        self.cond_gate, self.adj_gate = threading.Event(), threading.Event()
        self.cond_gate.set(), self.adj_gate.set()
        self.cond_calls = self.adj_calls = 0
        self.status, self.menu_id, self.checklist = status, menu_id, checklist
        self.engine = RiskEngine()
        self.svc = IntakeService(self.engine, lambda a: None, adjust_fn=self.adjust, condition_fn=self.condition)

    def adjust(self, ctx):
        self.adj_calls += 1
        assert self.adj_gate.wait(10)
        return A.adjust_structured(ctx)

    def resolve(self, terms):
        if self.checklist:
            return [ResolvedCondition(typed=terms[0], status="checklist", checklist=self.checklist)]
        return [ResolvedCondition(typed=t, canonical="Sickle cell disease", vocabulary="nlm_conditions", code="D57",
                                  status=self.status) for t in terms]

    def draft(self, code, canonical):
        pick = DraftPick(vital="hr", bound="high", menu_id=self.menu_id)
        r = DraftedRule(code=code, canonical=canonical, picks=[pick], sources=SRC, evidence_label="medium")
        return SimpleNamespace(rule=r, abstained=False, failed={}, infra_error=None, from_store=False)

    def condition(self, ctx):
        self.cond_calls += 1
        assert self.cond_gate.wait(10)
        return S.process(ctx, resolve_fn=self.resolve, draft_fn=self.draft)

    def hr(self, pid="p1"):
        return self.engine.ranges[pid].hr

    async def settle(self):
        await asyncio.gather(*self.svc._tasks)


async def test_submit_returns_at_once_with_structured_limits_while_conditions_run():
    w = World()
    w.cond_gate.clear()
    await w.svc.submit(rec("sickle cell disease"))
    assert w.hr().safe_high == 90 and w.svc.card("p1")["conditions"]["state"] == "pending"
    w.cond_gate.set()
    await w.settle()
    assert w.svc.card("p1")["conditions"]["state"] == "done"


async def test_draft_narrows_the_safe_edge_only_and_shows_on_the_card():
    w = World()
    await w.svc.submit(rec("sickle cell disease"))
    await w.settle()
    hr = w.hr()
    assert hr.safe_high == 85 and hr.danger_high == 131  # warning tier: danger edge untouched
    assert any("unreviewed" in r for r in hr.reasons)
    card = w.svc.card("p1")
    assert card["conditions"]["resolution"].items[0].code == "D57"
    drafted = [i for i in card["i15_items"] if i.rule_id == "draft:D57"]
    assert drafted and drafted[0].unreviewed is True and drafted[0].sources == SRC


async def test_the_draft_survives_the_adjuster_landing_after_the_conditions():
    w = World()
    w.adj_gate.clear()
    await w.svc.submit(rec("sickle cell disease"))
    for _ in range(100):  # conditions finish while the adjuster is still blocked
        if w.svc.card("p1")["conditions"]["state"] == "done":
            break
        await asyncio.sleep(0.02)
    assert w.hr().safe_high == 85
    w.adj_gate.set()
    await w.settle()
    assert w.hr().safe_high == 85  # the adjuster's apply must not wipe the draft


async def test_the_draft_survives_the_adjuster_landing_before_the_conditions():
    w = World()
    w.cond_gate.clear()
    await w.svc.submit(rec("sickle cell disease"))
    await asyncio.sleep(0.2)
    w.cond_gate.set()
    await w.settle()
    assert w.hr().safe_high == 85


async def test_resubmit_with_the_same_conditions_keeps_the_draft_and_does_not_rerun():
    w = World()
    await w.svc.submit(rec("sickle cell disease"))
    await w.settle()
    await w.svc.submit(rec("Sickle cell disease ", cc="cough and fever"))
    assert w.hr().safe_high == 85  # applied immediately, before any background work
    await w.settle()
    assert w.cond_calls == 1 and w.hr().safe_high == 85


async def test_resubmit_with_other_conditions_drops_the_old_draft():
    w = World()
    await w.svc.submit(rec("sickle cell disease"))
    await w.settle()
    await w.svc.submit(rec())  # the condition was removed
    assert w.hr().safe_high == 90
    await w.settle()
    assert w.hr().safe_high == 90 and w.svc.card("p1")["conditions"] is None


async def test_a_stale_condition_result_is_dropped_after_a_quick_resubmit():
    w = World()
    w.cond_gate.clear()
    await w.svc.submit(rec("sickle cell disease"))
    await w.svc.submit(rec())  # edited before the first lookup finished
    w.cond_gate.set()
    await w.settle()
    assert w.hr().safe_high == 90 and w.svc.stale_dropped >= 1


async def test_checklist_match_sets_the_flag_on_the_context_and_draws_no_limit():
    w = World(checklist="hypertension")
    await w.svc.submit(rec("high blood pressure"))
    await w.settle()
    assert "hypertension" in w.svc.card("p1")["context"].conditions
    assert w.hr().danger_high == 131 and not any("draft:" in str(r) for r in w.hr().reasons or [])


async def test_unavailable_lookup_changes_nothing_and_says_so():
    w = World(status="unavailable")
    await w.svc.submit(rec("sickle cell disease"))
    await w.settle()
    assert w.hr().safe_high == 90
    assert w.svc.card("p1")["conditions"]["resolution"].items[0].status == "unavailable"


async def test_a_crashing_condition_step_leaves_the_structured_result_in_place():
    w = World()
    w.condition = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    w.svc._condition_fn = w.condition
    await w.svc.submit(rec("sickle cell disease"))
    await w.settle()
    assert w.hr().safe_high == 90 and w.svc.card("p1")["conditions"]["state"] == "failed"


async def test_no_custom_conditions_never_calls_the_condition_step():
    w = World()
    await w.svc.submit(rec())
    await w.settle()
    assert w.cond_calls == 0 and w.svc.card("p1")["conditions"] is None


async def test_scenario_patients_skip_the_condition_step():
    w = World()
    await w.svc.submit(rec("sickle cell disease"), structured_only=True)
    await w.settle()
    assert w.cond_calls == 0
