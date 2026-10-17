"""Replay eICU stays through the stub engine with no intake (I13 every second, I6 on each row),
print the NEWS2 path, and write fixtures/eicu_i9.jsonl (recorded I9 stand-in for T4 / Fetch.ai).
Usage: uv run python -m scripts.replay_fixture [patient_id]"""
import sys

from backend.fixtures import DIR, iter_i13, load_i6, stay_rows, load_stays
from backend.risk_engine.engine import RiskEngine

rows = load_i6()
only = sys.argv[1] if len(sys.argv) > 1 else None
eng = RiskEngine()
i9_out = []
for stay in load_stays():
    pid = stay["patient_id"]
    srows = stay_rows(rows, pid)
    by_ts = {r.minute_ts: r for r in srows}
    path, levels = [], {}
    for w in iter_i13(srows):  # speed: no sleeping, fast-forwarded
        i14 = eng.on_second(w)
        if w.window_end_ts in by_ts:
            i9 = eng.on_minute(by_ts[w.window_end_ts])
            i9_out.append(i9.model_dump_json())
            levels[i9.level] = levels.get(i9.level, 0) + 1
            path.append(i14.news2)
    if only in (None, pid):
        print(pid, stay["outcome"], "levels", levels, "peak NEWS2", max(p for p in path if p is not None))
        print("  path every ~hour:", path[::12])
(DIR / "eicu_i9.jsonl").write_text("".join(l + "\n" for l in i9_out))
print(f"wrote {len(i9_out)} I9 rows")
