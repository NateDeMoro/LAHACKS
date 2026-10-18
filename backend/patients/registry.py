"""Patient registry: who is on the board, when they arrived, whether they were called in, and their I9 history.
Use when a route needs the list of patients or a patient's vitals history since arrival."""
from datetime import datetime

from backend.contracts import Model, PatientContext, RiskResult


class PatientRow(Model):
    patient_id: str
    name: str | None = None
    arrival_ts: datetime | None = None
    bed: str | None = None
    wearable_id: int | None = None
    called_in_ts: datetime | None = None
    simulated: bool = False


class PatientRegistry:
    def __init__(self):
        self._rows: dict[str, PatientRow] = {}
        self._history: dict[str, list[RiskResult]] = {}

    def upsert(self, ctx: PatientContext, bed: str | None, simulated: bool) -> None:
        old = self._rows.get(ctx.patient_id)
        self._rows[ctx.patient_id] = PatientRow(
            patient_id=ctx.patient_id, name=ctx.name, arrival_ts=ctx.arrival_ts, bed=bed,
            wearable_id=ctx.wearable_id, simulated=simulated, called_in_ts=old.called_in_ts if old else None)

    def rows(self) -> list[PatientRow]:
        return list(self._rows.values())

    def get(self, patient_id: str) -> PatientRow | None:
        return self._rows.get(patient_id)

    def mark_called_in(self, patient_id: str, ts: datetime) -> PatientRow | None:
        row = self._rows.get(patient_id)
        if row:
            row.called_in_ts = ts
        return row

    def add_history(self, risk: RiskResult) -> None:
        self._history.setdefault(risk.patient_id, []).append(risk)

    def history(self, patient_id: str) -> list[RiskResult]:
        return self._history.get(patient_id, [])

    def forget_simulated(self) -> list[str]:
        gone = [p for p, r in self._rows.items() if r.simulated]
        for p in gone:
            del self._rows[p]
            self._history.pop(p, None)
        return gone
