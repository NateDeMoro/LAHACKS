"""Play one sample patient's run to the console, scored with the real NEWS2 scorer.
Use when checking a run script or the player without ingest or a dashboard.
Usage:
  uv run python -m scripts.simulate_run u1 [--length 60] [--every 10] [--fast]
--length sets the run length in seconds (default from config); --fast skips the one-second waits."""
import argparse
import asyncio

from backend.risk_engine import news2
from backend.simulator.controller import SimController
from backend.simulator.profiles import PROFILES


class PrintSink:
    def __init__(self, triage, every):
        self.triage, self.every, self.count = triage, every, 0

    def ingest(self, reading, source):
        if self.count % self.every == 0:
            total, _ = news2.score(
                resp_rate=reading.resp_rate, spo2=reading.spo2, hr=reading.hr, temp_c=reading.temp_c,
                sbp=self.triage.sbp, alertness=self.triage.alertness, on_oxygen=self.triage.on_oxygen)
            print(f"{self.count:>5}s  hr {reading.hr:>5g}  resp {reading.resp_rate:>3g}  "
                  f"spo2 {reading.spo2:>3g}  temp {reading.temp_c:>4.1f}  NEWS2 {total}  [{source}]")
        self.count += 1

    def set_run_state(self, patient_id, state):
        print(f"run state: {state}")

    def seed_trend_history(self, patient_id, rows):
        print(f"trend pre-roll: {len(rows)} rows, {rows[0].minute_ts:%H:%M} to {rows[-1].minute_ts:%H:%M}")


async def _instant(_delay):
    await asyncio.sleep(0)


async def main(args):
    profile = PROFILES[args.profile]
    print(f"{profile.id} {profile.name} ({profile.tier}); expected NEWS2 at 0/30/60/100%: "
          f"{profile.script.expect.news2}; {profile.script.expect.alerts}")
    controller = SimController(PrintSink(profile.record.triage, args.every),
                               **({"sleep": _instant} if args.fast else {}))
    controller.start(args.profile, length_s=args.length)
    await controller.wait()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("profile", choices=list(PROFILES))
    p.add_argument("--length", type=int)
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--fast", action="store_true")
    asyncio.run(main(p.parse_args()))
