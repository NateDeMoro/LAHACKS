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


class UnknownWearable(ValueError):
    pass


class IntakeService:
    def __init__(self, engine: RiskEngine, on_assign: Callable[[WearableAssignment], None], *,
                 cfg: Config = CONFIG, adjust_fn: Callable[[PatientContext], A.Outcome] = A.adjust):
        self._engine, self._on_assign, self._adjust = engine, on_assign, adjust_fn
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
                 "patient_id": self._by_wearable.get(w)} for w in self.wearer_ids()]

    def card(self, patient_id: str) -> dict | None:
        """Profile card: I4, current I8, I5, I15 items and adjuster state. None for an unknown patient."""
        c = self._card.get(patient_id)
        if c is None:
            return None
        return {"context": c["ctx"], "ranges": self._engine.ranges.get(patient_id), "i5": c["i5"],
                "i15_items": c["i15"].items, "adjuster": c["state"]}

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
        ranges = self._engine.on_intake(ctx, i5)
        if self._engine.ranges_listener:
            self._engine.ranges_listener(ranges)

    async def submit(self, rec: IntakeRecord) -> WearableAssignment:
        """Use when POST /intake arrives. Needs the running event loop. Raises UnknownWearable."""
        if rec.wearable_id not in self._valid:
            raise UnknownWearable(rec.wearable_id)
        rec = rec.model_copy(update={"patient_id": rec.patient_id or f"pt-{secrets.token_hex(3)}",
                                     "arrival_ts": rec.arrival_ts or now_la()})
        ctx = self._build_context(rec)
        pid = ctx.patient_id
        seq = self._seq[pid] = self._seq.get(pid, 0) + 1
        assignment = self._assign(pid, rec.wearable_id)
        self._on_assign(assignment)
        out = A.adjust_structured(ctx)
        self._card[pid] = {"ctx": ctx, "i5": out.i5, "i15": out.i15, "state": PENDING}
        self._apply(ctx, out.i5)
        task = asyncio.create_task(self._finish(ctx, seq))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return assignment

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
        self._card[pid].update(i5=out.i5, i15=out.i15, state=DONE if out.llm_ok else STRUCTURED_ONLY)
        self._apply(ctx, out.i5)
