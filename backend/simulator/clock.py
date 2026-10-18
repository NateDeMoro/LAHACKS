"""Simulated clock for the waiting-room scenario. Use when a patient's time must run ahead of the wall clock."""
from datetime import datetime, timedelta

from backend.timeutil import now_la


class SimClock:
    """Wall time plus an offset, or a fixed time while a skip is being replayed."""

    def __init__(self):
        self._offset = timedelta(0)
        self._frozen: datetime | None = None

    def __call__(self) -> datetime:
        return self._frozen if self._frozen is not None else now_la() + self._offset

    def freeze(self, ts: datetime) -> None:
        self._frozen = ts

    def anchor(self, ts: datetime) -> None:
        """Run live again, with sim time `ts` being right now."""
        self._frozen = None
        self._offset = ts - now_la()
