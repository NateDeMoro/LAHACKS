"""Plays a simulated run into a RunSink, one reading per second, in process."""
import asyncio
import time
from datetime import datetime, timedelta

from backend.contracts import MinuteSummary, VitalsReading
from backend.simulator.models import RunSink, Sample


class RunPlayer:
    def __init__(self, sink: RunSink, *, now=time.monotonic, sleep=asyncio.sleep):
        self._sink = sink
        self._now = now
        self._sleep = sleep

    async def play(
        self,
        *,
        patient_id: str,
        wearable_id: int,
        start_ts: datetime,
        samples: list[Sample],
        preroll: list[MinuteSummary],
    ) -> None:
        if preroll:
            self._sink.seed_trend_history(patient_id, preroll)
        self._sink.set_run_state(patient_id, "running")
        try:
            t0 = self._now()
            for i, s in enumerate(samples):
                # Scheduled from t0, not from the last send, so slow sends do not stretch the run.
                await self._sleep(max(0, t0 + i - self._now()))
                reading = VitalsReading(
                    wearable_id=wearable_id,
                    ts=start_ts + timedelta(seconds=i),
                    hr=s.hr,
                    resp_rate=s.resp_rate,
                    spo2=s.spo2,
                    temp_c=s.temp_c,
                    contact=True,
                )
                self._sink.ingest(reading, "simulator")
        finally:
            # Also runs on cancel (a stop); the CancelledError keeps propagating after this.
            self._sink.set_run_state(patient_id, "ended")
