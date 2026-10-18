"""Write fixtures/wearer_drift_i6.jsonl: synthetic one-minute I6 for the fixture wearer (demo-001).
30 calm minutes, then heart rate drifts up 14 bpm over 30 minutes, staying inside the NEWS2 normal range.
SpO2 and temperature are normal simulated values (the demo simulator fills them).
Use when checking that the personal baseline learns a calm patient and flags a slow drift.
Usage: uv run python -m scripts.build_wearer_fixture"""
import json
import random

from backend.fixtures import DIR
from backend.timeutil import offset_to_ts

rnd = random.Random(7)
sim = random.Random(8)  # separate stream so the heart rate and breathing series are unchanged
rows = []
for i in range(60):
    hr = 72 + (14 * (i - 30) / 30 if i >= 30 else 0) + rnd.gauss(0, 1.5)
    rows.append(dict(patient_id="demo-001", minute_ts=offset_to_ts(i).isoformat(), hr=round(hr, 1),
                     resp_rate=round(15 + rnd.gauss(0, 0.8), 1),
                     spo2=round(min(100, max(96, 98 + sim.gauss(0, 0.5)))),
                     temp_c=round(36.8 + sim.gauss(0, 0.1), 1), clean_seconds=60))
(DIR / "wearer_drift_i6.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
print(f"wrote {len(rows)} rows")
