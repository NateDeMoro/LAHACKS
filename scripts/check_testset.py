"""Validate the labeled adjuster test set (B2) and print coverage. Use when editing fixtures/adjuster/*.jsonl
or models/rules.json, before the blind second pass, and before scoring the adjuster.
Usage:
  uv run python -m scripts.check_testset                      # full check; nonzero if any case is unchecked
  uv run python -m scripts.check_testset --allow-unchecked    # structure and coverage only
  uv run python -m scripts.check_testset --export-blind PATH  # intakes without labels, for the blind second pass
  uv run python -m scripts.check_testset --second-pass PATH   # compare a JSONL of {id, expected} and record agreement"""
import argparse
import json
import sys
from collections import Counter

from backend.adjuster.testset import DIR, RULES_PATH, TestCase
from backend.contracts import RulesFile
from backend.risk_engine.ranges import DANGER

MIN_FIRES = {"test": 5, "dev": 2}  # per rule, per split
MIN_NEAR_MISSES = 2  # per rule, across splits; tag near_miss_<rule_id>
MIN_TAGS = {"negation": 8, "past_use": 5, "slang": 6, "brand_name": 6, "misspelling": 6, "conflicting": 5,
            "nothing_relevant": 12, "multi_rule": 10, "injection": 4, "unmatched_med": 5}
SPLIT_SIZE = {"dev": 30, "test": 70}
BLIND_FIELDS = ["id", "age", "sex", "pregnant", "conditions", "medications", "drug_classes",
                "unmatched_medications", "chief_complaint"]


def read(split):
    path = DIR / f"{split}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def write(split, rows):
    (DIR / f"{split}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def check_rules(rules):
    errors = []
    for r in rules:
        for a in r.adjustments or []:
            low, high = DANGER[a.vital]
            edge = low if a.bound == "low" else high
            if edge is None:
                continue  # no edge today: any value adds one
            if (a.bound == "high" and a.value >= edge) or (a.bound == "low" and a.value <= edge):
                errors.append(f"rule {r.id}: {a.vital} {a.bound} {a.value} does not tighten NEWS2 edge {edge}")
    return errors


def labels(expected):
    return {(e["rule_id"], e["source"]) for e in expected}


def second_pass(path):
    theirs = {}
    for l in open(path):
        if l.strip():
            row = json.loads(l)
            theirs[row["id"]] = row["expected"]
    total = agree = 0
    for split in ("dev", "test"):
        rows = read(split)
        for r in rows:
            if r["id"] not in theirs:
                continue
            total += 1
            r["second_pass_agrees"] = labels(r["expected"]) == labels(theirs[r["id"]])
            agree += r["second_pass_agrees"]
            if not r["second_pass_agrees"]:
                print(f"DISAGREE {r['id']}: {r['chief_complaint']!r}")
                print(f"   first : {sorted(labels(r['expected']))}")
                print(f"   second: {sorted(labels(theirs[r['id']]))}")
        write(split, rows)
    print(f"second pass: {agree}/{total} agree ({100 * agree / max(total, 1):.0f}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-unchecked", action="store_true")
    ap.add_argument("--export-blind")
    ap.add_argument("--second-pass")
    args = ap.parse_args()
    if args.second_pass:
        return second_pass(args.second_pass)

    errors = []
    rules = RulesFile(**json.loads(RULES_PATH.read_text())).rules
    rule_ids = [r.id for r in rules]
    errors += check_rules(rules)

    cases = {}
    for split in ("dev", "test"):
        cases[split] = []
        for i, raw in enumerate(read(split), 1):
            try:
                case = TestCase(**raw)
            except Exception as e:
                errors.append(f"{split} line {i}: {str(e).splitlines()[0]}")
                continue
            if case.split != split:
                errors.append(f"{case.id}: split field {case.split} in {split}.jsonl")
            cases[split].append(case)
    all_cases = cases["dev"] + cases["test"]

    if args.export_blind:
        with open(args.export_blind, "w") as f:
            for c in all_cases:
                d = c.model_dump()
                f.write(json.dumps({k: d[k] for k in BLIND_FIELDS}) + "\n")
        print(f"wrote {len(all_cases)} blind intakes to {args.export_blind}")

    for split, n in SPLIT_SIZE.items():
        if len(cases[split]) != n:
            errors.append(f"{split}: {len(cases[split])} cases, expected {n}")
    ids = Counter(c.id for c in all_cases)
    errors += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    texts = Counter(c.chief_complaint.strip().lower() for c in all_cases)
    errors += [f"duplicate complaint: {t[:50]!r}" for t, n in texts.items() if n > 1]

    for c in all_cases:
        seen = set()
        for e in c.expected:
            if e.rule_id not in rule_ids:
                errors.append(f"{c.id}: unknown rule {e.rule_id}")
            if e.rule_id in seen:
                errors.append(f"{c.id}: rule {e.rule_id} listed twice")
            seen.add(e.rule_id)
            if e.source == "structured" and e.quote is not None:
                errors.append(f"{c.id}: structured label {e.rule_id} has a quote")
            if e.source == "text":
                if not e.quote:
                    errors.append(f"{c.id}: text label {e.rule_id} has no quote")
                elif e.quote not in c.chief_complaint:
                    errors.append(f"{c.id}: quote not in complaint: {e.quote!r}")
        if (len(c.expected) > 1) != ("multi_rule" in c.tags):
            errors.append(f"{c.id}: multi_rule tag does not match {len(c.expected)} labels")
        if not c.expected and "near_miss" not in " ".join(c.tags) and "nothing_relevant" not in c.tags \
                and "injection" not in c.tags:
            errors.append(f"{c.id}: no labels and no near_miss / nothing_relevant / injection tag")

    fires = {s: Counter(e.rule_id for c in cases[s] for e in c.expected) for s in cases}
    tags = Counter(t for c in all_cases for t in set(c.tags))
    print(f"{'rule':26s} {'dev':>4s} {'test':>5s} {'near-miss':>10s}")
    for rid in rule_ids:
        nm = tags[f"near_miss_{rid}"]
        print(f"{rid:26s} {fires['dev'][rid]:4d} {fires['test'][rid]:5d} {nm:10d}")
        for s in cases:
            if fires[s][rid] < MIN_FIRES[s]:
                errors.append(f"{rid}: fires in {fires[s][rid]} {s} cases, need {MIN_FIRES[s]}")
        if nm < MIN_NEAR_MISSES:
            errors.append(f"{rid}: {nm} near-misses, need {MIN_NEAR_MISSES}")
    print(f"\n{'tag':20s} {'count':>5s} {'min':>4s}")
    for t, m in MIN_TAGS.items():
        print(f"{t:20s} {tags[t]:5d} {m:4d}")
        if tags[t] < m:
            errors.append(f"tag {t}: {tags[t]}, need {m}")
    print(f"\ncases: dev {len(cases['dev'])}, test {len(cases['test'])}")

    unchecked = [c.id for c in all_cases if c.checked_by is None]
    disagree = [c.id for c in all_cases if c.second_pass_agrees is False]
    pending = [c.id for c in all_cases if c.second_pass_agrees is None]
    print(f"unchecked by a human: {len(unchecked)}; second pass: {len(disagree)} disagree, "
          f"{len(pending)} not yet compared")
    if disagree:
        print("  disagreements:", ", ".join(disagree))

    for e in errors:
        print("ERROR", e)
    if errors:
        sys.exit(1)
    if unchecked and not args.allow_unchecked:
        print("FAIL: unchecked cases remain")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
