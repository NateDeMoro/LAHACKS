"""Frozen evidence store: one JSON file of drafted rules and abstentions, keyed on the condition code, menu
version, prompt version and model. Use so a repeat condition gives the same limits with no fetch or model
call. Same pattern as the adjuster cache: a missing, corrupt or stale file is a miss, never an error."""
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.contracts import DraftedRule

_LOCK = threading.Lock()


@dataclass(frozen=True)
class Stored:
    rule: DraftedRule | None  # None is a stored abstention
    failed: dict[str, list[str]]


def key(code: str, menu_version: int | None, prompt_version: str, model: str) -> str:
    return hashlib.sha256(json.dumps([code, menu_version, prompt_version, model]).encode()).hexdigest()


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(path: Path, k: str) -> Stored | None:
    try:
        entry = _read(path)[k]
        rule = DraftedRule.model_validate(entry["rule"]) if entry["rule"] is not None else None
        return Stored(rule, {str(g): list(v) for g, v in entry["failed"].items()})
    except Exception:  # missing key, bad shape or schema-stale entry: a miss
        return None


def put(path: Path, k: str, rule: DraftedRule | None, failed: dict[str, list[str]]) -> None:
    with _LOCK:
        data = _read(path)
        data[k] = {"rule": rule.model_dump(mode="json") if rule else None, "failed": failed}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, path)
        except OSError:  # a failed cache write must not stop intake
            pass
