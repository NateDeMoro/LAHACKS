"""Score the custom-condition lookup layer against fixtures/conditions/lookup.jsonl.
Use when changing backend/conditions/lookup.py, its synonym table or the match threshold.
Usage:
  uv run python -m scripts.score_conditions --selftest   # recorded NLM responses, offline
  uv run python -m scripts.score_conditions --live       # real NLM API: a smoke test, not a safety proof
  uv run python -m scripts.score_conditions --record     # re-record fixtures/conditions/nlm_*.json from the live API
Counts are over a small hand-labeled set; read them as a smoke test."""
import argparse
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from backend.conditions import lookup

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "conditions"
CASES = FIXTURES / "lookup.jsonl"
LABELS = ("real", "invented", "checklist", "ambiguous", "injection")


def fixture_path(url: str) -> Path:
    term = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["terms"][0]
    return FIXTURES / f"nlm_{re.sub(r'[^a-z0-9]+', '_', term.lower()).strip('_')[:60]}.json"


def fixture_fetch(url: str, timeout: float) -> object:
    """A missing file raises, so an unrecorded term shows up as 'unavailable' rather than a silent not_found."""
    return json.loads(fixture_path(url).read_text())


def recording_fetch(url: str, timeout: float) -> object:
    data = lookup.http_get(url, timeout)
    fixture_path(url).write_text(json.dumps(data, ensure_ascii=False) + "\n")
    return data


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def status_of(case: dict, fetch) -> str:
    out = lookup.resolve([case["typed"]], fetch=fetch)
    return out[0].status if out else "dropped"


def is_known_miss(case: dict) -> bool:
    return case["note"].startswith("known miss")


def report(cases: list[dict], statuses: list[str]) -> int:
    """Prints per-label counts; returns how many mismatches are not documented known misses."""
    unexplained = 0
    print(f"{'label':<10} {'cases':>5} {'as expected':>12}   statuses")
    for label in LABELS:
        rows = [(c, s) for c, s in zip(cases, statuses) if c["label"] == label]
        hits = sum(s == c["expected_status"] for c, s in rows)
        print(f"{label:<10} {len(rows):>5} {hits:>9}/{len(rows):<3} {dict(Counter(s for _, s in rows))}")
    for c, s in zip(cases, statuses):
        if s != c["expected_status"]:
            tag = "known miss" if is_known_miss(c) else "UNEXPECTED"
            unexplained += tag == "UNEXPECTED"
            print(f"  {tag}: {c['typed'][:60]!r} expected {c['expected_status']}, got {s}")
    return unexplained


def measured(cases: list[dict], statuses: list[str]) -> None:
    def n(label, ok):
        rows = [s for c, s in zip(cases, statuses) if c["label"] == label]
        return f"{sum(s in ok for s in rows)} of {len(rows)}"
    print("\nMeasured on this set (smoke test):")
    print(f"  real conditions resolved (found or checklist): {n('real', ('found', 'checklist'))}")
    print(f"  invented names answered not_found: {n('invented', ('not_found',))}")
    print(f"  checklist terms mapped to the checklist: {n('checklist', ('checklist',))}")
    print(f"  injection strings answered not_found: {n('injection', ('not_found',))}")
    print(f"  unavailable answers: {sum(s == 'unavailable' for s in statuses)} of {len(statuses)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--record", action="store_true")
    args = ap.parse_args()
    fetch = fixture_fetch if args.selftest else recording_fetch if args.record else None
    cases = load_cases()
    statuses = [status_of(c, fetch) for c in cases]
    print(f"{'recorded fixtures' if args.selftest else 'live NLM API'}, {len(cases)} cases\n")
    unexplained = report(cases, statuses)
    measured(cases, statuses)
    return 1 if args.selftest and unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
