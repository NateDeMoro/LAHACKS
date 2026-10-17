"""Turns Polar H10 heart-rate frames into I1 readings and feeds beats to the breathing estimator."""
from datetime import datetime
from itertools import accumulate

from backend.config import CONFIG, ReceiverConfig
from backend.contracts import VitalsReading
from backend.timeutil import LA


class FrameProcessor:
    def __init__(self, cfg: ReceiverConfig = CONFIG.receiver, estimator=None):
        if estimator is None:
            from receiver.breathing import BreathingEstimator  # lazy: tests pass a fake
            estimator = BreathingEstimator(cfg.breathing)
        self._cfg = cfg
        self._est = estimator
        self._contact = True
        self._first_frame_s: float | None = None
        self._last_beat_s: float | None = None

    def on_frame(self, tstamp_ns: int, avg_hr: int, rr_ms: list[int],
                 sensor_contact: bool | None) -> VitalsReading:
        t_end = tstamp_ns / 1e9
        if self._first_frame_s is None:
            self._first_frame_s = t_end
        if rr_ms:
            self._last_beat_s = t_end

        contact = sensor_contact if sensor_contact is not None else self._judge_contact(t_end, avg_hr)
        if not contact:
            self._set_contact(False)
            return self._reading(tstamp_ns, contact=False, rr_ms=[])

        self._contact = True
        if rr_ms:
            start = t_end - sum(rr_ms) / 1000
            self._est.add_beats([start + c / 1000 for c in accumulate(rr_ms)], rr_ms)
        return self._reading(tstamp_ns, contact=True, hr=avg_hr, rr_ms=list(rr_ms),
                             resp_rate=self._est.estimate(t_end, contact=True))

    def no_strap(self, now_ns: int) -> VitalsReading:
        self._set_contact(False)
        return self._reading(now_ns, contact=False)

    def _judge_contact(self, t_end: float, avg_hr: int) -> bool:
        if avg_hr == 0:
            return False
        # Counting from the first frame keeps a fresh start from being flagged early.
        since = self._last_beat_s if self._last_beat_s is not None else self._first_frame_s
        return t_end - since <= self._cfg.no_beat_timeout_s

    def _set_contact(self, contact: bool) -> None:
        if self._contact and not contact:
            self._est.reset()
        self._contact = contact

    def _reading(self, ts_ns: int, contact: bool, hr=None, rr_ms=None, resp_rate=None) -> VitalsReading:
        return VitalsReading(
            wearable_id=self._cfg.wearable_id,
            ts=datetime.fromtimestamp(ts_ns / 1e9, LA),
            hr=hr,
            rr_intervals_ms=rr_ms,
            contact=contact,
            resp_rate=resp_rate,
        )
