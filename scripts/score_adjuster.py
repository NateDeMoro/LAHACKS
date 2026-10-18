"""Score the context adjuster (B3) against the labeled test set, or self-test it offline.
Use when changing backend/adjuster/ or the adjuster prompt.
Usage:
  uv run python -m scripts.score_adjuster --selftest                 # offline checks on a stub, no API
  uv run python -m scripts.score_adjuster --split dev --offline      # structured rules only, no API
  uv run --env-file .env python -m scripts.score_adjuster --split dev [--repeat 3]   # live, cache off
Test split: score it once, after tuning on dev. Never writes the evaluation log; per-case results go to --out."""
import argparse
import json
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path

from backend.adjuster import adjuster as A
from backend.adjuster import rules as R
from backend.adjuster.testset import TestCase, load_cases
from backend.contracts import ContextAdjustments, PatientContext, PatientRanges
from backend.risk_engine import ranges
from backend.risk_engine.ranges import DANGER

DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-natedemoro-LAHACKS/4f249dbb-676b-4217-9cff-ed50221fe8f4/scratchpad")


def to_ctx(c: TestCase) -> PatientContext:
    return PatientContext(patient_id=c.id, age=c.age, sex=c.sex, pregnant=c.pregnant, conditions=c.conditions,
                          medications=c.medications, drug_classes=c.drug_classes,
                          unmatched_medications=c.unmatched_medications, chief_complaint=c.chief_complaint)


def pairs_of(i15) -> set[tuple[str, str]]:
    return {(it.rule_id, "text" if it.quote else "structured") for it in i15.items}


def loosening(i5: ContextAdjustments) -> int:
    return sum(not R.tightens(a.vital, a.bound, a.value) for a in i5.adjustments or [])


def score(cases: list[TestCase], outs: list, label: str, verbose: bool) -> dict:
    tp = fp = fn = exact = loose = dropped = 0
    lat = []
    rows = []
    for c, o in zip(cases, outs):
        got, want = pairs_of(o.i15), {(e.rule_id, e.source) for e in c.expected}
        tp, fp, fn = tp + len(got & want), fp + len(got - want), fn + len(want - got)
        exact += got == want
        loose += loosening(o.i5)
        dropped += len(getattr(o, "dropped", []))
        if getattr(o, "latency_s", 0):
            lat.append(o.latency_s)
        rows.append({"id": c.id, "got": sorted(got), "want": sorted(want), "dropped": getattr(o, "dropped", [])})
        if verbose and got != want:
            print(f"  {c.id}: extra {sorted(got - want)} missing {sorted(want - got)} :: {c.chief_complaint[:90]!r}")
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"{label}: cases {len(cases)}  precision {p:.3f}  recall {r:.3f}  exact {exact}/{len(cases)} "
          f"({exact / len(cases):.0%})  tp {tp} fp {fp} fn {fn}  dropped proposals {dropped}  loosening {loose}")
    if lat:
        print(f"  latency median {statistics.median(lat):.1f}s, slowest {max(lat):.1f}s")
    return {"precision": p, "recall": r, "exact": exact, "rows": rows}


def selftest():
    # structured firing on dev cases
    dev = {c.id: c for c in load_cases("dev")}
    fired = {k: sorted(R.structured_facts(to_ctx(c))) for k, c in dev.items()}
    assert fired["d01"] == ["age65", "beta_blocker"], fired["d01"]
    assert fired["d02"] == ["beta_blocker"], fired["d02"]
    assert fired["d03"] == [], fired["d03"]  # slang beta blocker is text only
    # merge: stricter wins on a shared edge, order follows rules.json
    m = R.merge("p", ["pregnancy", "beta_blocker"])
    assert [(a.rule_id, a.vital, a.bound, a.value) for a in m.adjustments] == \
        [("beta_blocker", "hr", "high", 110), ("pregnancy", "sbp", "high", 160)], m
    m = R.merge("p", ["age65", "chemo_fever", "steroid_immunosuppressed"])
    temp = [a for a in m.adjustments if a.vital == "temp_c"]
    assert len(temp) == 1 and temp[0].value == 37.8 and temp[0].rule_id == "age65", m
    # merge drops a loosening value (spo2 low edge is 91; 85 would loosen)
    from backend.contracts import RuleAdjustment, RuleSpec
    bad = [RuleSpec(id="x", adjustments=[RuleAdjustment(vital="hr", bound="high", value=140),
                                         RuleAdjustment(vital="temp_c", bound="high", value=38.5)])]
    assert [(a.vital, a.value) for a in R.merge("p", ["x"], bad).adjustments] == [("temp_c", 38.5)]
    # outcome: same rules, any order, same bytes
    a = A.adjust_structured(PatientContext(patient_id="p", age=70, drug_classes=["opioid", "beta_blocker"], pregnant=True))
    assert [i.rule_id for i in a.i15.items] == ["opioid", "age65", "beta_blocker", "pregnancy"]
    assert a.i15.model == A.STRUCTURED_ONLY and a.i15.quote_found is None
    assert all(i.quote is None for i in a.i15.items)
    # applying I5 to I8
    pop = ranges.score0_ranges("p")
    adj = ranges.apply_i5(pop, ContextAdjustments(patient_id="p", adjustments=[
        {"rule_id": "age65", "vital": "temp_c", "bound": "high", "value": 37.8},
        {"rule_id": "opioid", "vital": "resp_rate", "bound": "low", "value": 10},
        {"rule_id": "bad", "vital": "hr", "bound": "high", "value": 140},     # loosens: ignored
        {"rule_id": "bad", "vital": "spo2", "bound": "high"}]))               # no value: ignored
    assert adj.temp_c.danger_high == 37.8 and adj.temp_c.safe_high == 37.7, adj.temp_c
    assert adj.resp_rate.danger_low == 10 and adj.resp_rate.safe_low == 12
    assert adj.hr.danger_high == DANGER["hr"][1] and adj.hr.reasons == []
    assert adj.temp_c.reasons and pop.temp_c.danger_high is None  # input untouched
    print("selftest passed: structured firing, merge, order, tighten-only I5 on I8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--split", choices=["dev", "test"])
    ap.add_argument("--offline", action="store_true", help="structured rules only, no API")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.split:
        ap.error("--split or --selftest required")
    cases = load_cases(a.split)
    verbose = a.split == "dev"
    if a.offline:
        outs = [A.adjust_structured(to_ctx(c)) for c in cases]
        score(cases, outs, f"{a.split} structured only", verbose)


if __name__ == "__main__":
    main()
