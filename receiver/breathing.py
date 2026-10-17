"""Breathing rate from heartbeat intervals (respiratory sinus arrhythmia) over a rolling window."""
from collections.abc import Sequence

import numpy as np
from scipy.signal import butter, medfilt, sosfiltfilt

from backend.config import CONFIG, BreathingConfig


class BreathingEstimator:
    def __init__(self, cfg: BreathingConfig = CONFIG.receiver.breathing):
        self.cfg = cfg
        self._times: list[float] = []
        self._rr: list[float] = []
        self.last_reason = "few_beats"

    def add_beats(self, beat_times_s: Sequence[float], rr_ms: Sequence[float]) -> None:
        for t, rr in zip(beat_times_s, rr_ms):
            # Out-of-order or non-finite beats would break interpolation, so skip them.
            if not (np.isfinite(t) and np.isfinite(rr)) or rr <= 0:
                continue
            if self._times and t <= self._times[-1]:
                continue
            self._times.append(float(t))
            self._rr.append(float(rr))
        if self._times:
            keep_from = self._times[-1] - self.cfg.window_s
            n_old = sum(t <= keep_from for t in self._times)
            del self._times[:n_old], self._rr[:n_old]

    def reset(self) -> None:
        self._times.clear()
        self._rr.clear()
        self.last_reason = "few_beats"

    def estimate(self, now_s: float, contact: bool = True) -> float | None:
        value, self.last_reason = self._estimate(now_s, contact)
        return None if value is None else round(value, 1)

    def _estimate(self, now: float, contact: bool) -> tuple[float | None, str]:
        c = self.cfg
        if not contact:
            return None, "no_contact"
        times, rr = np.array(self._times), np.array(self._rr)
        m = (times > now - c.window_s) & (times <= now)
        t, r = times[m], rr[m]
        if len(r) < max(c.min_beats, c.window_s / 3):
            return None, "few_beats"
        if np.max(np.diff(np.concatenate([[now - c.window_s], t, [now]]))) > c.max_gap_s:
            return None, "gap"

        r = self._repair_skips(r)
        tg = np.arange(t[0], t[-1], 1 / c.resample_hz)
        x = np.interp(tg, t, r)
        x -= x.mean()
        sos = butter(2, c.bandpass_hz, btype="band", fs=c.resample_hz, output="sos")
        x = sosfiltfilt(sos, x)
        x = (x - x.mean()) * np.hanning(len(x))
        power = np.abs(np.fft.rfft(x, c.nfft)) ** 2
        freq = np.fft.rfftfreq(c.nfft, 1 / c.resample_hz)

        in_band = (freq >= c.search_hz[0]) & (freq <= c.search_hz[1])
        fb, pb = freq[in_band], power[in_band]
        if pb.sum() <= 0:
            return None, "unclear"
        i = int(np.argmax(pb))
        if i == 0 or i == len(pb) - 1:
            return None, "edge_peak"
        peak_hz = fb[i]

        mean_hr_hz = len(r) / (t[-1] - t[0])
        if peak_hz > c.hr_guard * mean_hr_hz:
            return None, "above_hr_nyquist"

        near = np.abs(fb - peak_hz) <= max(0.03, 1.5 / c.window_s)
        far = np.abs(fb - peak_hz) > max(0.05, 2.0 / c.window_s)
        rival = pb[far].max() if far.any() else 0.0
        if pb[near].sum() / pb.sum() < c.band_power_frac or pb[i] / (rival + 1e-12) < c.peak_ratio:
            return None, "unclear"

        # Parabola through log power of the peak and its neighbours gives a finer frequency.
        a, b, d = np.log(pb[i - 1:i + 2] + 1e-12)
        shift = 0.5 * (a - d) / (a - 2 * b + d)
        return (peak_hz + shift * (fb[1] - fb[0])) * 60, "ok"

    def _repair_skips(self, rr: np.ndarray) -> np.ndarray:
        if len(rr) < 7:
            return rr
        med = medfilt(rr, 7)
        bad = np.abs(rr - med) > self.cfg.skip_tolerance * med
        return np.where(bad, med, rr)
