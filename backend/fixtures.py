"""Fixture loaders. Use when a component needs I1/I2/I4/I6/I13 stand-ins."""
import json
from datetime import timedelta
from pathlib import Path
from typing import Iterator

from backend.contracts import IntakeRecord, LiveWindow, PeriodSummary, PatientContext, VitalsReading

DIR = Path(__file__).resolve().parent.parent / "fixtures"
HOLD = timedelta(minutes=5)  # how long an I6 value stands in for the live window


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_i6(path: Path = DIR / "eicu_i6.jsonl") -> list[PeriodSummary]:
    return [PeriodSummary(**r) for r in _jsonl(path)]


def load_i1(path: Path = DIR / "i1_messages.jsonl") -> list[VitalsReading]:
    return [VitalsReading(**r) for r in _jsonl(path)]


def load_intake() -> IntakeRecord:
    return IntakeRecord(**json.loads((DIR / "intake_i2.json").read_text()))


def load_context() -> PatientContext:
    return PatientContext(**json.loads((DIR / "context_i4.json").read_text()))


def load_stays(path: Path = DIR / "eicu_stays.json") -> list[dict]:
    return json.loads(path.read_text())


def stay_rows(rows: list[PeriodSummary], patient_id: str) -> list[PeriodSummary]:
    return sorted((r for r in rows if r.patient_id == patient_id), key=lambda r: r.period_ts)


def iter_i13(rows: list[PeriodSummary]) -> Iterator[LiveWindow]:
    """Expand one stay's I6 rows (sorted) into one I13 per second. Each I6 value is held
    for up to 5 minutes, then null. Replay speed is up to the caller."""
    if not rows:
        return
    t, end, i = rows[0].period_ts, rows[-1].period_ts + HOLD, 0
    while t <= end:
        while i + 1 < len(rows) and rows[i + 1].period_ts <= t:
            i += 1
        r = rows[i]
        live = r.period_ts <= t < r.period_ts + HOLD
        yield LiveWindow(
            patient_id=r.patient_id, window_end_ts=t,
            hr=r.hr if live else None, resp_rate=r.resp_rate if live else None,
            spo2=r.spo2 if live else None, temp_c=r.temp_c if live else None,
            clean_seconds=r.clean_seconds if live else None)
        t += timedelta(seconds=1)
