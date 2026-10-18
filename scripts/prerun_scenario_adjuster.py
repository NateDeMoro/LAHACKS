"""Pre-run the context adjuster (one StepFun call) for Dorothy Klein's scenario profile and save the validated
text findings to fixtures/scenario_adjuster_c2.json, so the demo shows them at once instead of waiting 25-45 s.
Use when her complaint or the adjuster prompt changes. Run: uv run --env-file .env python -m scripts.prerun_scenario_adjuster"""
import json
from pathlib import Path

from backend.adjuster import adjuster as A
from backend.contracts import PatientContext
from backend.intake.lookup import classify
from backend.simulator.scenario import SCENARIO_PATIENTS

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "scenario_adjuster_c2.json"


def main():
    p = next(p for p in SCENARIO_PATIENTS if p.key == "c2")
    rec = p.record.model_copy(update={"patient_id": "prerun-c2", "name": p.name, "wearable_id": p.wearable_id})
    classes, unmatched = classify(rec.medications or [])
    bmi = round(rec.weight_kg / (rec.height_cm / 100) ** 2, 1) if rec.height_cm and rec.weight_kg else None
    ctx = PatientContext(**{**rec.model_dump(), "bmi": bmi, "drug_classes": classes, "unmatched_medications": unmatched})
    out = A.adjust(ctx, use_cache=False, write_log=False)
    print("llm_ok:", out.llm_ok, "latency:", round(out.latency_s, 1), "dropped:", out.dropped)
    items = [{"rule_id": i.rule_id, "fact": i.fact, "quote": i.quote} for i in out.i15.items or [] if i.quote]
    OUT.write_text(json.dumps({"model": out.i15.model, "items": items}, indent=2) + "\n")
    print(json.dumps(items, indent=2))


main()
