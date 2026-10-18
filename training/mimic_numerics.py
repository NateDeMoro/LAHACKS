"""Read and clean MIMIC-III matched-subset numerics records into per-minute segments for the T6 fast model.
Use when building training data (training/train_fast.py) or checking how records were filtered.

Steps per record: read with wfdb -> map signal names (HR with PULSE fallback, RESP, SpO2) -> physiologic limits
(same as scripts/build_eicu_fixtures.LIMITS) -> 1 Hz records collapse to minute medians (source rate kept) ->
SpO2 probe-artifact filter -> split at gaps -> neonate filter. All drops are counted in a Counter.
Data: MIMIC-III Waveform Database Matched Subset (Moody et al., PhysioNet), ODbL.
"""
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.risk_engine import news2
from scripts.build_eicu_fixtures import LIMITS

log = logging.getLogger("mimic_numerics")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mimic3wdb"
CACHE = ROOT / "data" / "processed" / "mimic_segments.pkl"

VITALS = ("hr", "resp_rate", "spo2")
LIMIT = {"hr": LIMITS["heartrate"], "resp_rate": LIMITS["respiration"], "spo2": LIMITS["sao2"],
         "sbp": (40, 300)}
# normalized signal name (lowercase, letters and digits only) -> (vital, priority); lower priority wins when merging
NAME_MAP = {"hr": ("hr", 0), "pulse": ("hr", 1), "resp": ("resp_rate", 0), "spo2": ("spo2", 0),
            "nbpsys": ("sbp", 0)}
MIN_SAMPLES_PER_MINUTE = 30   # of 60 one-second samples needed for a minute median
GAP_MINUTES = 10              # no HR, breathing or SpO2 for more than this splits a segment
MIN_SEGMENT_MINUTES = 50      # need 15 minutes of history plus a 20-minute look-ahead
SPO2_DROP = 10                # a fall bigger than this in one minute is a probe artifact...
SPO2_MAX_REJECT = 4           # ...unless it persists beyond this many minutes (then it is real)


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass
class Segment:
    patient: str
    record: str
    rate: str            # "1s" or "1min": source sampling rate
    start: int           # first minute, relative to the record start
    hr: np.ndarray
    resp_rate: np.ndarray
    spo2: np.ndarray
    sbp: np.ndarray      # non-invasive systolic, NaN except where recorded (used only for the alert budget)

    def __len__(self):
        return len(self.hr)

    def vital(self, name):
        return getattr(self, name)


def map_signals(sig_names, p_signal):
    """Return {vital: [channel arrays in merge order]} using case-insensitive names.
    Use when checking name handling; duplicate channels are kept (merged later), unknown names ignored."""
    chans: dict[str, list[tuple[int, int, np.ndarray]]] = {}
    for idx, name in enumerate(sig_names):
        hit = NAME_MAP.get(norm_name(name))
        if hit:
            chans.setdefault(hit[0], []).append((hit[1], idx, p_signal[:, idx]))
    return {v: [c for _, _, c in sorted(lst, key=lambda x: (x[0], x[1]))] for v, lst in chans.items()}


def to_minutes(chans, samples_per_minute: int):
    """Per vital: clean each channel to physiologic limits, take minute medians, merge duplicates (first channel
    that has a value wins, so PULSE only fills where HR is missing). Returns {vital: minute array with NaN gaps}."""
    out = {}
    for v, lst in chans.items():
        lo, hi = LIMIT[v]
        merged = None
        for ch in lst:
            x = np.where((ch >= lo) & (ch <= hi), ch, np.nan)
            n = len(x) // samples_per_minute * samples_per_minute
            if samples_per_minute == 1:
                m = x
            else:
                blocks = x[:n].reshape(-1, samples_per_minute)
                with np.errstate(all="ignore"):
                    m = np.nanmedian(blocks, axis=1)
                m[np.isfinite(blocks).sum(axis=1) < MIN_SAMPLES_PER_MINUTE] = np.nan
            merged = m if merged is None else np.where(np.isfinite(merged), merged, m)
        out[v] = merged
    return out


def spo2_artifact_filter(x: np.ndarray, counts: Counter | None = None) -> np.ndarray:
    """Null a minute whose SpO2 is more than SPO2_DROP below the last accepted value within GAP_MINUTES,
    for at most SPO2_MAX_REJECT consecutive minutes (a longer low stretch is accepted as real)."""
    x = x.copy()
    last, last_i, rejected = np.nan, -10**9, 0
    for i in range(len(x)):
        v = x[i]
        if not np.isfinite(v):
            continue
        if np.isfinite(last) and i - last_i <= GAP_MINUTES and last - v > SPO2_DROP and rejected < SPO2_MAX_REJECT:
            x[i] = np.nan
            rejected += 1
            if counts is not None:
                counts["spo2_artifact_minutes"] += 1
            continue
        last, last_i, rejected = v, i, 0
    return x


def split_segments(mins: dict, patient: str, record: str, rate: str, counts: Counter) -> list[Segment]:
    n = max(len(a) for a in mins.values())
    arr = {v: np.full(n, np.nan) for v in (*VITALS, "sbp")}
    for v, a in mins.items():
        arr[v][: len(a)] = a
    obs = np.isfinite(arr["hr"]) | np.isfinite(arr["resp_rate"]) | np.isfinite(arr["spo2"])
    idx = np.nonzero(obs)[0]
    segs = []
    if len(idx) == 0:
        return segs
    cut = np.nonzero(np.diff(idx) > GAP_MINUTES)[0]
    counts["gap_splits"] += len(cut)
    bounds = np.split(idx, cut + 1)
    for b in bounds:
        a, z = b[0], b[-1] + 1
        if z - a < MIN_SEGMENT_MINUTES:
            counts["segments_too_short"] += 1
            continue
        segs.append(Segment(patient, record, rate, int(a), *(arr[v][a:z].copy() for v in (*VITALS, "sbp"))))
    return segs


def in_danger(hr, rr, sp):
    """Boolean arrays of NEWS2 score-3 minutes per vital (NaN is not in danger). Uses the engine's own bands."""
    def mask(x, fn):
        out = np.zeros(len(x), bool)
        for i in np.nonzero(np.isfinite(x))[0]:
            out[i] = fn(float(x[i])) == 3
        return out
    return mask(hr, news2.score_hr), mask(rr, news2.score_rr), mask(sp, news2.score_spo2)


def is_neonate(seg: Segment) -> bool:
    """Drop rule: first-hour median HR > 130 or breathing > 30, or > 40% of observed minutes in danger."""
    first = slice(0, 60)
    with np.errstate(all="ignore"):
        hr_med = np.nanmedian(seg.hr[first]) if np.isfinite(seg.hr[first]).any() else np.nan
        rr_med = np.nanmedian(seg.resp_rate[first]) if np.isfinite(seg.resp_rate[first]).any() else np.nan
    if hr_med > 130 or rr_med > 30:
        return True
    dh, dr, ds = in_danger(seg.hr, seg.resp_rate, seg.spo2)
    obs = np.isfinite(seg.hr) | np.isfinite(seg.resp_rate) | np.isfinite(seg.spo2)
    return (dh | dr | ds).sum() > 0.4 * obs.sum()


def read_record(hea: Path, counts: Counter) -> list[Segment]:
    import wfdb
    rec = wfdb.rdrecord(str(hea.with_suffix("")))
    spm = round(rec.fs * 60)
    if spm < 1:
        counts["records_unsupported_rate"] += 1
        return []
    rate = "1s" if spm > 1 else "1min"
    chans = map_signals(rec.sig_name, rec.p_signal)
    if not all(v in chans for v in VITALS):
        counts["records_missing_vital"] += 1
        return []
    mins = to_minutes(chans, spm)
    mins["spo2"] = spo2_artifact_filter(mins["spo2"], counts)
    patient = hea.parent.name
    return split_segments(mins, patient, hea.stem, rate, counts)


def load_segments(root: Path = RAW, use_cache: bool = True):
    """Return (kept segments, counts) for every complete record under root. Cached because 1 Hz files are slow.
    Use when starting training or the label check."""
    import pickle
    if use_cache and CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    counts: Counter = Counter()
    kept: list[Segment] = []
    for hea in sorted(root.glob("p*/p*/*.hea")):
        dats = set(re.findall(r"^(\S+\.dat)\s", hea.read_text(), flags=re.M))
        if not all((hea.parent / d).exists() for d in dats):
            counts["records_incomplete_download"] += 1
            continue
        counts["records_read"] += 1
        try:
            segs = read_record(hea, counts)
        except Exception as e:
            counts["records_read_error"] += 1
            log.warning("skip %s: %s", hea.name, e)
            continue
        for s in segs:
            counts["segments"] += 1
            counts[f"segments_{s.rate}"] += 1
            if is_neonate(s):
                counts["segments_dropped_neonate_or_danger"] += 1
                counts[f"minutes_dropped_neonate_or_danger"] += len(s)
                continue
            counts["segments_kept"] += 1
            counts["minutes_kept"] += len(s)
            kept.append(s)
    counts["patients_kept"] = len({s.patient for s in kept})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps((kept, counts)))
    return kept, counts
