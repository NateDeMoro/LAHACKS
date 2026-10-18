"""Offline check of the medication lookup against the B2 test set, the sample patients and the wearer
fixture. Use when changing backend/intake/lookup.py. Usage: uv run python -m scripts.check_lookup
Exits non-zero if a check fails; the wearer fixture comparison is report only."""
import sys

from backend.adjuster.testset import load_cases
from backend.fixtures import load_context
from backend.intake.lookup import classify
from backend.simulator.profiles import PROFILES

failures = []


def fail(msg):
    failures.append(msg)
    print("FAIL", msg)


cases = load_cases("dev") + load_cases("test")
for c in cases:
    got, unmatched = classify(c.medications)
    label_un = set(c.unmatched_medications)
    if missed := set(c.drug_classes) - set(got):
        fail(f"{c.id}: missed classes {sorted(missed)}")
    if surprise := set(unmatched) - label_un:
        fail(f"{c.id}: unmatched not in label {sorted(surprise)}")
    # an extra class is fine only when it comes from a medication the label lists as unmatched
    extra = set(got) - set(c.drug_classes)
    explained = set()
    for m in c.medications:
        if m in label_un:
            explained |= set(classify([m])[0])
    if extra - explained:
        fail(f"{c.id}: surprise classes {sorted(extra - explained)}")
print(f"B2 cases checked: {len(cases)}")

for med in ("Flovent inhaler", "hydrocortisone cream", "timolol eye drops", "albuterol inhaler"):
    if classify([med]) != ([], []):
        fail(f"route exclusion: {med} -> {classify([med])}")

bare = {"prednisone 5mg tablet": "prednisone", "methylprednisolone 4 mg tabs": "methylprednisolone",
        "prednisone 10 mg PO daily": "prednisone", "morphine IV": "morphine", "Percocet 5/325": "percocet",
        "fentanyl 25 mcg/hr patch": "fentanyl", "tramadol 50 mg q6h": "tramadol",
        "prednisone 40 mg x5 days": "prednisone", "oxycodone as needed": "oxycodone",
        "sertraline 50 mg once a day": "sertraline", "metoprolol 25 mg tablet": "metoprolol"}
for med, base in bare.items():
    if classify([med]) != classify([base]) or classify([med])[1] or not classify([med])[0]:
        fail(f"extra words: {med} -> {classify([med])}, bare {base} -> {classify([base])}")
for med in ("insulin glargine 20 units", "aspirin 81"):
    if classify([med]) != ([], []):
        fail(f"known no-class: {med} -> {classify([med])}")
for med in ("metaprolol 25 mg tablet", "oxycotin", "predisone 5 mg"):
    if classify([med])[1] != [med]:
        fail(f"misspelling matched: {med} -> {classify([med])}")

expect = {"u1": ["beta_blocker"], "c1": ["beta_blocker"], "c2": []}
for pid, p in PROFILES.items():
    got, unmatched = classify(p.record.medications or [])
    print(f"sample {pid}: {p.record.medications} -> {got} unmatched {unmatched}")
    if pid in expect and got != expect[pid]:
        fail(f"sample {pid}: expected {expect[pid]}, got {got}")
    if unmatched:
        fail(f"sample {pid}: unmatched {unmatched}")

fx = load_context()
got, unmatched = classify(fx.medications or [])
print(f"wearer fixture: lookup {got} unmatched {unmatched}; fixtures/context_i4.json has {fx.drug_classes} "
      f"unmatched {fx.unmatched_medications} (report only; 'biguanide' is outside the I4 vocabulary)")

print("FAILED" if failures else "check_lookup passed")
sys.exit(1 if failures else 0)
