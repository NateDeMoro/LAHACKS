"""Labeled test-set models for the context adjuster (B2). Use when loading, scoring or checking
fixtures/adjuster/*.jsonl. Rules for labeling: notes/adjuster-labeling-guide.md."""
import json
from pathlib import Path
from typing import Literal

from backend.contracts import Condition, Model, Sex

DIR = Path(__file__).resolve().parents[2] / "fixtures" / "adjuster"
RULES_PATH = Path(__file__).resolve().parents[2] / "models" / "rules.json"


class ExpectedRule(Model):
    rule_id: str
    source: Literal["structured", "text"]
    quote: str | None = None  # exact words from chief_complaint; null for structured


class TestCase(Model):
    __test__ = False  # not a pytest class
    id: str
    split: Literal["dev", "test"]
    age: float
    sex: Sex
    pregnant: bool | None = None
    conditions: list[Condition] = []
    medications: list[str] = []
    drug_classes: list[str] = []
    unmatched_medications: list[str] = []
    chief_complaint: str
    expected: list[ExpectedRule] = []
    tags: list[str] = []
    drafter: str
    second_pass_agrees: bool | None = None
    checked_by: str | None = None
    notes: str | None = None


def load_cases(split: str) -> list[TestCase]:
    path = DIR / f"{split}.jsonl"
    return [TestCase(**json.loads(l)) for l in path.read_text().splitlines() if l.strip()]
