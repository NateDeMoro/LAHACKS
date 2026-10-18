"""Intake service (S5, reduced): I2 in, I3 and I4 out. Use when a nurse submits an intake record and the
patient needs a wearable, a context for the engine and the adjuster's limits.

Order follows the component-map adjuster call-order note: structured I5 is applied at once, the LLM part
runs in a worker thread and a second on_intake applies the full I5 on the event loop. The engine is only
ever called on the event loop. A background result is applied only if it is still the patient's latest
intake, so a quick resubmit with an edited complaint is never overwritten by the slower first call."""
import asyncio
import logging
import secrets
from typing import Callable

from backend.adjuster import adjuster as A
from backend.config import CONFIG, Config
from backend.contracts import (AdjustmentEvidence, ContextAdjustments, IntakeRecord, PatientContext,
                               WearableAssignment)
from backend.intake.lookup import classify
from backend.risk_engine.engine import RiskEngine
from backend.timeutil import now_la

log = logging.getLogger(__name__)

PENDING, DONE, STRUCTURED_ONLY = "pending", "done", "structured only"
FAILED = "failed"


def _terms_key(terms: list[str] | None) -> tuple[str, ...]:
    return tuple(sorted({" ".join(t.lower().split()) for t in terms or [] if t.strip()}))


def default_condition_fn(ctx: PatientContext):
    """Real lookup and evidence step; imported here so the intake service loads without them."""
    from backend.conditions import evidence, lookup, service
    from backend.conditions import normalize
    norm = normalize.for_config()
    return service.process(ctx, resolve_fn=lambda terms: lookup.resolve(terms, normalize_fn=norm),
                           draft_fn=lambda code, name: evidence.draft(code, name, vocabulary="nlm_conditions"))


class UnknownWearable(ValueError):
    pass


class IntakeService:
    def __init__(self, engine: RiskEngine, on_assign: Callable[[WearableAssignment], None], *,
                 cfg: Config = CONFIG, adjust_fn: Callable[[PatientContext], A.Outcome] = A.adjust,
                 on_submit: Callable[[PatientContext], None] = lambda ctx: None,
                 condition_fn: Callable[[PatientContext], object] = default_condition_fn):
        self._engine, self._on_assign, self._adjust, self._on_submit = engine, on_assign, adjust_fn, on_submit
        self._condition_fn = condition_fn
        self._cond: dict[str, dict] = {}  # patient -> {key: typed terms, outcome}: drafts survive a resubmit
        self._sim_wearables = set(cfg.simulator.scenario_wearable_ids)
        self._presets: dict[str, Callable[[PatientContext], A.Outcome]] = {}  # scenario patients with a pre-run adjuster result
        self._structured_only: set[str] = set()  # scenario patients: no LLM call, so ranges never move mid-demo
        self._labels = dict(cfg.beds.labels)
        self._valid = set(self._labels) | {cfg.receiver.wearable_id}
        self._by_wearable: dict[int, str] = {}
        self._wearable_of: dict[str, int] = {}
        self._seq: dict[str, int] = {}
        self._card: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()
        self.stale_dropped = 0

    def wearer_ids(self) -> list[int]:
        return sorted(self._valid)

    def wearables(self) -> list[dict]:
        return [{"wearable_id": w, "label": self._labels.get(w, f"Strap {w}"),
                 "patient_id": self._by_wearable.get(w), "simulated": w in self._sim_wearables} for w in self.wearer_ids()]

    def card(self, patient_id: str) -> dict | None:
        """Profile card: I4, current I8, I5, I15 items and adjuster state. None for an unknown patient."""
        c = self._card.get(patient_id)
        if c is None:
            return None
        cond = c.get("cond")
        drafted = list(cond.evidence_items) if cond else []
        return {"context": c["ctx"], "ranges": self._engine.ranges.get(patient_id), "i5": c["i5"],
                "i15_items": [*(c["i15"].items or []), *drafted], "adjuster": c["state"],
                "conditions": self._conditions_card(c)}

    @staticmethod
    def _conditions_card(c: dict) -> dict | None:
        if not c["ctx"].custom_conditions:
            return None
        cond = c.get("cond")
        return {"state": c.get("cond_state", PENDING), "resolution": cond.resolution if cond else None,
                "suggestions": cond.suggestions if cond else [], "infra_errors": cond.infra_errors if cond else []}

    def _assign(self, patient_id: str, wearable_id: int) -> WearableAssignment:
        old_patient = self._by_wearable.get(wearable_id)
        if old_patient and old_patient != patient_id:
            del self._wearable_of[old_patient]
        old_wearable = self._wearable_of.get(patient_id)
        if old_wearable is not None and old_wearable != wearable_id:
            del self._by_wearable[old_wearable]
        self._by_wearable[wearable_id], self._wearable_of[patient_id] = patient_id, wearable_id
        return WearableAssignment(wearable_id=wearable_id, patient_id=patient_id, assigned_ts=now_la())

    def _build_context(self, rec: IntakeRecord) -> PatientContext:
        classes, unmatched = classify(rec.medications or [])
        bmi = None
        if rec.height_cm and rec.weight_kg:
            bmi = round(rec.weight_kg / (rec.height_cm / 100) ** 2, 1)
        return PatientContext(**{**rec.model_dump(), "bmi": bmi, "drug_classes": classes,
                                 "unmatched_medications": unmatched})

    def _apply(self, ctx: PatientContext, i5: ContextAdjustments):
        """on_intake rebuilds ranges from the I5 it is given, so every apply carries the patient's drafts too."""
        cond = self._card.get(ctx.patient_id, {}).get("cond")
        if cond and cond.adjustments:
            i5 = i5.model_copy(update={"adjustments": [*(i5.adjustments or []), *cond.adjustments]})
        ranges = self._engine.on_intake(ctx, i5)
        if self._engine.ranges_listener:
            self._engine.ranges_listener(ranges)

    async def submit(self, rec: IntakeRecord, *, structured_only: bool = False,
                     preset: Callable[[PatientContext], A.Outcome] | None = None) -> WearableAssignment:
        """Use when POST /intake arrives. Needs the running event loop. Raises UnknownWearable.
        structured_only skips the LLM step (the scenario); preset supplies a pre-run adjuster result instead of the structured one;
        a resubmit keeps both choices and the first arrival time."""
        if rec.wearable_id not in self._valid:
            raise UnknownWearable(rec.wearable_id)
        prior = self._card.get(rec.patient_id) if rec.patient_id else None
        if structured_only:
            self._structured_only.add(rec.patient_id)
        structured_only = structured_only or rec.patient_id in self._structured_only
        if preset:
            self._presets[rec.patient_id] = preset
        preset = self._presets.get(rec.patient_id)
        rec = rec.model_copy(update={"patient_id": rec.patient_id or f"pt-{secrets.token_hex(3)}",
                                     "arrival_ts": rec.arrival_ts or (prior["ctx"].arrival_ts if prior else None) or now_la()})
        ctx = self._build_context(rec)
        pid = ctx.patient_id
        seq = self._seq[pid] = self._seq.get(pid, 0) + 1
        assignment = self._assign(pid, rec.wearable_id)
        self._on_assign(assignment)
        key = _terms_key(ctx.custom_conditions)
        kept = self._cond.get(pid)
        if not key or structured_only or (kept and kept["key"] != key):
            self._cond.pop(pid, None)  # conditions removed or changed: the old drafts no longer apply
            kept = None
        cond = kept["outcome"] if kept else None
        if cond and cond.checklist_flags:
            ctx = ctx.model_copy(update={"conditions": sorted({*(ctx.conditions or []), *cond.checklist_flags})})
        out = preset(ctx) if preset else A.adjust_structured(ctx)
        self._card[pid] = {"ctx": ctx, "i5": out.i5, "i15": out.i15, "state": PENDING, "cond": cond,
                           "cond_state": DONE if cond else PENDING}
        self._apply(ctx, out.i5)
        self._on_submit(ctx)
        if structured_only:
            self._card[pid]["state"] = DONE if preset else STRUCTURED_ONLY
            return assignment
        self._spawn(self._finish(ctx, seq))
        if key and not cond:
            self._spawn(self._finish_conditions(ctx, seq, key))
        return assignment

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finish_conditions(self, ctx: PatientContext, seq: int, key: tuple[str, ...]):
        """Lookup and evidence run off the loop; the result is applied on it, only if still the latest intake."""
        pid = ctx.patient_id
        try:
            outcome = await asyncio.to_thread(self._condition_fn, ctx)
        except Exception:  # the structured result stays in place
            log.exception("condition step failed for %s", pid)
            outcome = None
        if self._seq.get(pid) != seq:
            self.stale_dropped += 1
            return
        card = self._card[pid]
        if outcome is None:
            card["cond_state"] = FAILED
            return
        try:
            card["cond"], card["cond_state"] = outcome, DONE
            self._cond[pid] = {"key": key, "outcome": outcome}
            if outcome.checklist_flags:
                card["ctx"] = card["ctx"].model_copy(update={"conditions": sorted(
                    {*(card["ctx"].conditions or []), *outcome.checklist_flags})})
            self._apply(card["ctx"], card["i5"])
        except Exception:
            log.exception("condition apply failed for %s", pid)
            card["cond_state"] = FAILED

    async def _finish(self, ctx: PatientContext, seq: int):
        pid = ctx.patient_id
        try:
            out: A.Outcome = await asyncio.to_thread(self._adjust, ctx)
        except Exception:  # the adjuster falls back on LLM failure itself; anything else keeps the structured result
            log.exception("adjuster failed for %s", pid)
            out = None
        if self._seq.get(pid) != seq:
            self.stale_dropped += 1
            return
        if out is None:
            self._card[pid]["state"] = STRUCTURED_ONLY
            return
        try:
            self._card[pid].update(i5=out.i5, i15=out.i15, state=DONE if out.llm_ok else STRUCTURED_ONLY)
            self._apply(self._card[pid]["ctx"], out.i5)
        except Exception:
            log.exception("background apply failed for %s", pid)
            self._card[pid]["state"] = STRUCTURED_ONLY
