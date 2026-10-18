"""Download a seeded random sample of MIMIC-III matched-subset numerics records (.hea + .dat) for the T6 fast model.
Use when (re)building data/raw/mimic3wdb/ for training/train_fast.py. Safe to rerun: finished files are skipped.

Source: https://physionet.org/content/mimic3wdb-matched/1.0/ (open access, ODbL; Moody et al., PhysioNet).
Usage: python -m training.fetch_mimic_numerics --benchmark   # time 10 records first
       python -m training.fetch_mimic_numerics --patients 300 --workers 16
"""
import argparse
import logging
import random
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "mimic3wdb"
BASE = "https://physionet.org/files/mimic3wdb-matched/1.0/"
log = logging.getLogger("fetch_mimic")


def _get(url: str, dest: Path, tries: int = 4) -> int:
    """Download url to dest via temp file then rename; skips if dest exists. Returns bytes written (0 if skipped)."""
    if dest.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for i in range(tries):
        try:
            n = 0
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    n += len(chunk)
            part.rename(dest)
            return n
        except Exception as e:  # network blips are common on this server
            if i == tries - 1:
                raise
            log.warning("retry %s (%s)", url, e)
            time.sleep(2 * (i + 1))


def fetch_record(rec: str) -> tuple[str, int, int]:
    """rec like p00/p000020/p000020-2183-04-28-17-47n. Returns (rec, bytes, sig_rate_flag-less)."""
    d = rec.rsplit("/", 1)[0]
    hea = OUT / (rec + ".hea")
    n = _get(BASE + rec + ".hea", hea)
    text = hea.read_text()
    dats = set(re.findall(r"^(\S+\.dat)\s", text, flags=re.M))
    for dat in dats:
        n += _get(f"{BASE}{d}/{dat}", OUT / d / dat)
    return rec, n, len(dats)


def sample_records(n_patients: int, seed: int, per_patient: int) -> list[str]:
    cache = OUT / "RECORDS-numerics"
    _get(BASE + "RECORDS-numerics", cache)
    recs = [l.strip() for l in cache.read_text().splitlines() if l.strip()]
    by_patient: dict[str, list[str]] = {}
    for r in recs:
        by_patient.setdefault(r.split("/")[1], []).append(r)
    rng = random.Random(seed)
    pats = sorted(by_patient)
    rng.shuffle(pats)
    out = []
    for p in pats[:n_patients]:
        rs = by_patient[p][:]
        rng.shuffle(rs)
        out += sorted(rs[:per_patient])
    log.info("%d records in index, %d patients; sampled %d patients -> %d records",
             len(recs), len(pats), min(n_patients, len(pats)), len(out))
    return out


def run(recs: list[str], workers: int) -> None:
    t0, total, done, failed = time.time(), 0, 0, []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_record, r): r for r in recs}
        for f in as_completed(futs):
            try:
                _, n, _ = f.result()
                total += n
            except Exception as e:
                failed.append(futs[f])
                log.error("failed %s: %s", futs[f], e)
            done += 1
            if done % 10 == 0 or done == len(recs):
                dt = time.time() - t0
                log.info("%d/%d records, %.1f MB, %.1f KB/s overall, %d failed",
                         done, len(recs), total / 1e6, total / 1e3 / max(dt, 1e-9), len(failed))
    log.info("finished: %d ok, %d failed, %.1f MB in %.0f s", len(recs) - len(failed), len(failed),
             total / 1e6, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=300)
    ap.add_argument("--per-patient", type=int, default=1, help="max records downloaded per patient")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--benchmark", action="store_true", help="download 10 records only and print throughput")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    recs = sample_records(a.patients, a.seed, a.per_patient)
    if a.benchmark:
        recs = recs[:10]
    run(recs, a.workers)


if __name__ == "__main__":
    main()
