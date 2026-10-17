"""Hardware check 4: how does the strap show 'no contact'? Guided on/off/on test."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`
from bleak import BleakClient, BleakScanner
from bleakheart import HeartRate

from backend.config import CONFIG

PHASES = ["ON skin", "OFF skin", "ON skin again"]
ACTIONS = ["Keep the strap ON your skin", "LIFT the strap OFF your skin", "Put the strap BACK on your skin"]


async def run_phase(i, seconds, rec):
    print(f"\a\n== {ACTIONS[i]} for {seconds} s ==")
    rec.clear()
    for left in range(seconds, 0, -5):
        print(f"  {left} s left")
        await asyncio.sleep(min(5, left))
    return list(rec)


def summarize(name, frames):
    contact = {c for _, _, c in frames if c is not None}
    zero_hr = sum(1 for a, _, _ in frames if a == 0)
    with_rr = sum(1 for _, r, _ in frames if r)
    print(f"{name:<14} frames={len(frames):>3}  with_rr={with_rr:>3}  hr==0: {zero_hr:>3}  contact flag seen: {sorted(contact) or 'n/a'}")


async def main(prefix: str, seconds: int) -> int:
    print(f"Wear the strap. Looking for '{prefix}*'...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, adv: (d.name or adv.local_name or "").lower().startswith(prefix.lower()), timeout=10
    )
    if dev is None:
        print("FAIL: strap not found. Run scan.py first.")
        return 1
    rec = []

    def on_frame(f):
        contact = hr.good_contact.is_set() if hr.contact_detection else None
        rec.append((f[2][0], f[2][1], contact))

    try:
        async with BleakClient(dev) as client:
            hr = HeartRate(client, callback=on_frame, unpack=False)
            await hr.start_notify()
            results = [await run_phase(i, seconds, rec) for i in range(3)]
            await hr.stop_notify()
    except Exception as e:
        print(f"FAIL: connection problem ({e!r}). Close the Polar phone app and retry.")
        return 1
    print("\nResults:")
    for n, fr in zip(PHASES, results):
        summarize(n, fr)
    on, off, back = results
    if not on or not back:
        print("FAIL: no frames while the strap was on skin")
        return 1
    off_contact = {c for _, _, c in off}
    if hr.contact_detection and False in off_contact:
        how = "the strap sets its contact flag to False"
    elif not off:
        how = "frames stop completely"
    elif any(a == 0 for a, _, _ in off):
        how = "frames keep coming but heart rate reads 0"
    elif not any(r for _, r, _ in off):
        how = "frames keep coming but with no RR values"
    else:
        how = None
    if how is None:
        print("LOOK AT THIS: nothing changed while the strap was off. Was it really off skin and dry?")
        return 0
    print(f"Conclusion: with no contact, {how}.")
    print("PASS: no-contact is detectable" if any(r for _, r, _ in back) else "LOOK AT THIS: no RR after putting it back")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--seconds", type=int, default=15, help="length of each phase")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.seconds)))
