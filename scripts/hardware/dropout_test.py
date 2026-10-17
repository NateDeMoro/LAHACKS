"""Hardware check 6: how fast do we get frames back after the strap drops out?"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend`
from bleak import BleakClient, BleakScanner
from bleakheart import HeartRate

from backend.config import CONFIG

LIMIT_S = 30


async def connect(prefix, lost, frame):
    """Scan, connect, subscribe. Returns the client, or None if the strap was not found."""
    loop = asyncio.get_running_loop()
    dev = await BleakScanner.find_device_by_filter(
        lambda d, adv: (d.name or adv.local_name or "").lower().startswith(prefix.lower()), timeout=5
    )
    if dev is None:
        return None
    # Bleak may call this from another thread, so hop onto the loop.
    client = BleakClient(dev, disconnected_callback=lambda c: loop.call_soon_threadsafe(lost.set))
    await client.connect()
    await HeartRate(client, callback=lambda f: frame.set(), unpack=False).start_notify()
    return client


async def recover(prefix, lost, frame):
    """Retry until a frame arrives; returns seconds taken, or None after LIMIT_S."""
    t0 = time.monotonic()
    while (left := LIMIT_S - (time.monotonic() - t0)) > 0:
        lost.clear()
        frame.clear()
        try:
            if await asyncio.wait_for(connect(prefix, lost, frame), left):
                await asyncio.wait_for(frame.wait(), max(LIMIT_S - (time.monotonic() - t0), 0.1))
                return time.monotonic() - t0
        except (Exception, asyncio.TimeoutError) as e:
            print(f"  retrying ({e!r})")
        await asyncio.sleep(1)
    return None


async def main(prefix, rounds):
    lost, frame = asyncio.Event(), asyncio.Event()
    print(f"Wear the strap. Connecting to '{prefix}*'...")
    try:
        if not await connect(prefix, lost, frame):
            print("FAIL: strap not found. Run scan.py first.")
            return 1
        await asyncio.wait_for(frame.wait(), 10)
    except Exception as e:
        print(f"FAIL: could not connect ({e!r}). Close the Polar phone app and retry.")
        return 1
    times = []
    for i in range(1, rounds + 1):
        print(f"\a\nRound {i}: walk out of range or turn laptop Bluetooth OFF now.")
        await asyncio.wait_for(lost.wait(), 120)
        print("Disconnect detected. Come back / turn Bluetooth ON, then press Enter right away.")
        await asyncio.to_thread(input)
        took = await recover(prefix, lost, frame)
        times.append(took)
        print(f"Recovered in {took:.1f} s" if took else f"No frame within {LIMIT_S} s")
    ok = all(times)
    print(f"PASS: every recovery within {LIMIT_S} s" if ok else f"FAIL: a recovery took over {LIMIT_S} s")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", default=CONFIG.receiver.strap_name_prefix, help="strap name prefix")
    p.add_argument("--rounds", type=int, default=2, help="number of dropouts")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.prefix, a.rounds)))
