"""Hardware check 5: breathe to a metronome and see if BreathingEstimator finds the rate."""
import argparse
import asyncio
import statistics
import sys
import time
from collections import Counter
from itertools import accumulate
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`, `receiver`
from bleak import BleakClient, BleakScanner
from bleakheart import HeartRate

from backend.config import CONFIG

MAX_ERR = 1.5  # breaths/min
state = {"est": None, "t0": 0.0}


def on_frame(frame):
    est, rr = state["est"], frame[2][1]
    if est is None or not rr:
        return
    t_end = time.monotonic() - state["t0"]
    start = t_end - sum(rr) / 1000
    est.add_beats([start + c / 1000 for c in accumulate(rr)], rr)


async def run_rate(rate, seconds, estimator_cls, hr):
    est = state["est"] = estimator_cls()
    state["t0"] = t0 = time.monotonic()
    half, next_cue, next_est, out = 30 / rate, 0.0, 60.0, []
    inhale = True
    print(f"\a\n== {rate} breaths/min for {seconds} s: follow IN / OUT ==")
    while (now := time.monotonic() - t0) < seconds:
        if now >= next_cue:
            print("\aIN" if inhale else "OUT")
            inhale, next_cue = not inhale, next_cue + half
        if now >= next_est:
            next_est += 5
            contact = hr.good_contact.is_set() if hr.contact_detection else True
            out.append((est.estimate(now, contact=contact), est.last_reason))
        await asyncio.sleep(0.05)
    state["est"] = None
    return out


def report(rate, out):
    vals = [v for v, _ in out if v is not None]
    none_frac = 1 - len(vals) / len(out) if out else 1.0
    reasons = Counter(r for v, r in out if v is None).most_common(1)
    err = statistics.median(abs(v - rate) for v in vals) if vals else float("inf")
    mae = statistics.mean(abs(v - rate) for v in vals) if vals else float("nan")
    med = statistics.median(vals) if vals else float("nan")
    print(f"rate {rate}: median est {med:.1f}, MAE {mae:.2f}, median error {err:.2f}, "
          f"None {none_frac:.0%} (top reason: {reasons[0][0] if reasons else '-'})")
    return err <= MAX_ERR and none_frac <= 0.5


async def main(prefix, rates, seconds, rest):
    try:
        from receiver.breathing import BreathingEstimator
    except ImportError as e:
        print(f"FAIL: receiver.breathing is not written yet ({e}). Build it, then rerun.")
        return 1
    print(f"Wear the strap. Looking for '{prefix}*'...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, adv: (d.name or adv.local_name or "").lower().startswith(prefix.lower()), timeout=10
    )
    if dev is None:
        print("FAIL: strap not found. Run scan.py first.")
        return 1
    results = {}
    try:
        async with BleakClient(dev) as client:
            hr = HeartRate(client, callback=on_frame, unpack=False)
            await hr.start_notify()
            for rate in rates:
                print(f"\nRest and breathe normally for {rest} s...")
                await asyncio.sleep(rest)
                results[rate] = await run_rate(rate, seconds, BreathingEstimator, hr)
            await hr.stop_notify()
    except Exception as e:
        print(f"FAIL: connection problem ({e!r}). Close the Polar phone app and retry.")
        return 1
    print("\nResults:")
    ok = all([report(r, out) for r, out in results.items()])
    print("PASS: estimator tracks paced breathing" if ok else "FAIL: error over 1.5 breaths/min or too many None")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--rates", type=float, nargs="+", default=[6, 10, 15], help="breaths per minute")
    p.add_argument("--seconds", type=int, default=120, help="length of each rate")
    p.add_argument("--rest", type=int, default=15, help="rest between rates")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.rates, a.seconds, a.rest)))
