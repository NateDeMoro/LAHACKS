"""Hardware check 3: are frames steady and are the RR values sane?"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`
from bleak import BleakClient, BleakScanner
from bleakheart import HeartRate

from backend.config import CONFIG

MAX_GAP_S = 3.0
MAX_BAD_FRAC = 0.01


async def main(prefix: str, seconds: float) -> int:
    print(f"Wear the strap and sit still for {seconds:.0f} s. Looking for '{prefix}*'...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, adv: (d.name or adv.local_name or "").lower().startswith(prefix.lower()), timeout=10
    )
    if dev is None:
        print("FAIL: strap not found. Run scan.py first.")
        return 1
    times, rrs = [], []

    def on_frame(frame):
        times.append(time.monotonic())
        rrs.extend(frame[2][1])

    try:
        async with BleakClient(dev) as client:
            hr = HeartRate(client, callback=on_frame, unpack=False)
            await hr.start_notify()
            print("Connected. Recording...")
            await asyncio.sleep(seconds)
            await hr.stop_notify()
    except Exception as e:
        print(f"FAIL: connection problem ({e!r}). Close the Polar phone app and retry.")
        return 1
    if len(times) < 2:
        print("FAIL: fewer than 2 frames received")
        return 1
    gap = max(b - a for a, b in zip(times, times[1:]))
    bad = sum(1 for r in rrs if not 300 <= r <= 2000)
    bad_frac = bad / len(rrs) if rrs else 1.0
    print(f"frames per minute: {len(times) / seconds * 60:.1f}")
    print(f"longest gap between frames: {gap:.2f} s (limit {MAX_GAP_S})")
    print(f"rr values outside 300-2000 ms: {bad}/{len(rrs)} ({bad_frac:.1%}, limit {MAX_BAD_FRAC:.0%})")
    ok = gap <= MAX_GAP_S and bad_frac < MAX_BAD_FRAC
    print("PASS: steady frames, clean RR" if ok else "FAIL: gap too long or too many bad RR values")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--seconds", type=float, default=120, help="how long to record")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.seconds)))
