"""Hardware check 2: connect to the strap and print every heart-rate frame."""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`
from bleak import BleakClient, BleakScanner
from bleakheart import HeartRate

from backend.config import CONFIG


async def main(prefix: str, seconds: float) -> int:
    print(f"Wear the strap. Looking for '{prefix}*'...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, adv: (d.name or adv.local_name or "").lower().startswith(prefix.lower()), timeout=10
    )
    if dev is None:
        print("FAIL: strap not found. Run scan.py first.")
        return 1
    frames = []
    try:
        async with BleakClient(dev) as client:
            hr = HeartRate(client, callback=lambda f: on_frame(f, hr, frames), unpack=False)
            await hr.start_notify()
            print(f"Connected to {dev.name}. Printing frames for {seconds:.0f} s...")
            await asyncio.sleep(seconds)
            await hr.stop_notify()
    except Exception as e:
        print(f"FAIL: could not connect/stream ({e!r}).")
        print("Close the Polar phone app (and any other app using the strap); it allows one connection.")
        return 1
    n = len(frames)
    rr_frames = sum(1 for f in frames if f[1])
    print("\nWhat we learned:")
    print(f"  contact_detection supported: {hr.contact_detection}")
    print(f"  RR present: {'yes' if rr_frames else 'no'} ({rr_frames}/{n} frames)")
    print(f"  frames per second: {n / seconds:.2f}")
    print("If connecting fails, close the Polar phone app first.")
    ok = n > 0 and rr_frames > 0
    print("PASS: frames with RR arrived" if ok else "FAIL: no frames or no RR values")
    return 0 if ok else 1


def on_frame(frame, hr, frames):
    _, _, (avg, rr), _ = frame
    contact = hr.good_contact.is_set() if hr.contact_detection else "n/a"
    frames.append((avg, rr, contact))
    print(f"{time.strftime('%H:%M:%S')}  hr={avg:>3}  rr_ms={rr}  contact={contact}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--seconds", type=float, default=30, help="how long to stream")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.seconds)))
