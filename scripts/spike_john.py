"""Spike: replay John Chamberlain's scripted vitals through the real IngestService, RiskEngine and AlertLogic on a
fake clock, structured-only adjuster. Use when retuning John's keyframes (backend/simulator/scenario.py).
Run: uv run python -m scripts.spike_john [--seed N]"""
import sys
from datetime import datetime, timedelta

from backend.config import IngestConfig
from backend.contracts import IntakeRecord, PatientContext, Triage, VitalsReading
from backend.adjuster.adjuster import adjust_structured
from backend.ingest.service import IngestService
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine
from backend.simulator.generate import generate
from backend.simulator.scenario import JOHN_SCRIPT, SCENARIO_MINUTES
from backend.timeutil import LA

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=LA)


class Out:
    def __init__(self):
        self.i9, self.i10, self.i14 = [], [], {}

    def publish(self, t, m):
        if t == "I9":
            self.i9.append(m)
        elif t == "I10":
            self.i10.append(m)

    def write(self, *a, **k):
        pass


def main():
    script = JOHN_SCRIPT
    if "--seed" in sys.argv:
        script = script.model_copy(update={"seed": int(sys.argv[sys.argv.index("--seed") + 1])})
    now = [T0]
    out = Out()
    engine = RiskEngine()
    svc = IngestService(engine, AlertLogic(engine.config.alerts, engine.bed_label), out.publish, out,
                        IngestConfig(default_assignments={}), clock=lambda: now[0])
    rec = IntakeRecord(patient_id="john", name="John Chamberlain", wearable_id=1, arrival_ts=T0, age=54, sex="male",
                       height_cm=180, weight_kg=84, pregnant=False, conditions=[], medications=[],
                       chief_complaint="Feeling run down with a cough.",
                       triage=Triage(sbp=124, dbp=80, alertness="alert", pain=2, on_oxygen=False, level=3))
    ctx = PatientContext(**rec.model_dump())
    svc.assign(1, "john")
    engine.on_intake(ctx, adjust_structured(ctx).i5)
    shown = 0
    for i, s in enumerate(generate(script, SCENARIO_MINUTES * 60)):
        now[0] = T0 + timedelta(seconds=i + 1)
        svc.ingest(VitalsReading(wearable_id=1, ts=T0 + timedelta(seconds=i), hr=s.hr, resp_rate=s.resp_rate,
                                 spo2=s.spo2, temp_c=s.temp_c, contact=True), "simulator")
        svc.tick()
        while shown < len(out.i9):
            r = out.i9[shown]
            shown += 1
            m = (r.ts - T0).total_seconds() / 60
            v = r.vital_values
            print(f"m{m:02.0f} {r.level:7} n2={r.news2} hr={v.hr:g} rr={v.resp_rate} sp={v.spo2:g} t={v.temp_c:g} "
                  f"trend={r.trend_prob_fast and round(r.trend_prob_fast, 2)} {r.trend_tier} | {r.reason}")
        for a in out.i10:
            m = (a.ts - T0).total_seconds() / 60
            print(f"    ALERT m{m:.0f} {a.severity} {a.trigger} {'RESOLVED ' if a.resolved else ''}{a.message}")
        out.i10.clear()


main()
