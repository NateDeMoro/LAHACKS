"""Hardware check 1: can this laptop see the strap over Bluetooth?"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`
from bleak import BleakScanner

from backend.config import CONFIG


async def main(prefix: str, seconds: float) -> int:
    print(f"Wear the strap (wet the electrodes) and scan for {seconds:.0f} s...")
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = sorted(found.values(), key=lambda x: -x[1].rssi)
    hits = 0
    for dev, adv in rows:
        name = dev.name or adv.local_name or "(no name)"
        match = name.lower().startswith(prefix.lower())
        hits += match
        print(f"{'>>' if match else '  '} {name:<30} {adv.rssi:>4} dBm  {dev.address}")
    print(f"\n{len(rows)} devices seen, {hits} match '{prefix}'.")
    if not rows:
        print("Nothing at all. On macOS, give your terminal Bluetooth access:")
        print("System Settings > Privacy & Security > Bluetooth. Also wear the strap")
        print("with wet electrodes; it sleeps until it feels skin.")
    print("PASS: strap found" if hits else f"FAIL: no device named '{prefix}*'")
    return 0 if hits else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--seconds", type=float, default=10, help="scan length")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.seconds)))
