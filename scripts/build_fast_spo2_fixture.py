"""Write fixtures/fast_spo2_drop_i6.jsonl: synthetic one-minute I6 for a calm patient whose SpO2 slides.
30 calm minutes (SpO2 about 97), then SpO2 falls from 97 to 90 over 20 minutes; HR and breathing stay normal.
Use when checking the fast trend model: trend stays null for 15 clean minutes, then a warning appears before SpO2
reaches 91, and never urgent.
Usage: uv run python -m scripts.build_fast_spo2_fixture"""
import json
import random

from backend.fixtures import DIR
from backend.timeutil import offset_to_ts

rnd = random.Random(11)
rows = []
for i in range(50):
    spo2 = 97 if i < 30 else 97 - 7 * (i - 29) / 20
    rows.append(dict(patient_id="demo-spo2", period_ts=offset_to_ts(i).isoformat(), hr=round(74 + rnd.gauss(0, 1.2), 1),
                     resp_rate=round(15 + rnd.gauss(0, 0.6), 1), spo2=round(spo2 + rnd.gauss(0, 0.3), 1),
                     temp_c=36.8, clean_seconds=60))
(DIR / "fast_spo2_drop_i6.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
print(f"wrote {len(rows)} rows")
