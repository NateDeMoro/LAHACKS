"""Waiting-room scenario scripts (separate from the single-run scripts in profiles.py).
Keyframes are given in simulated minutes of the 60-minute scenario and converted to run fractions."""
from backend.simulator.models import Expect, Keyframe, RunScript, Track

SCENARIO_MINUTES = 60
_WOBBLE_STEP = {"hr": (2, 1), "resp_rate": (1, 1), "spo2": (0.8, 1), "temp_c": (0.05, 0.1)}


def minute_script(points: dict[str, list[tuple[float, float]]], seed: int, news2: list[int], alerts: str) -> RunScript:
    tracks = {
        v: Track(keyframes=[Keyframe(at=m / SCENARIO_MINUTES, value=x) for m, x in pts],
                 wobble=_WOBBLE_STEP[v][0], step=_WOBBLE_STEP[v][1])
        for v, pts in points.items()
    }
    return RunScript(tracks=tracks, seed=seed, expect=Expect(news2=news2, alerts=alerts))


# Steep-then-hold: change between minutes 12 and 22, hold just short of danger, then drop into danger from 31.
JOHN_POINTS = {
    "hr": [(0, 76), (12, 76), (22, 84), (31, 86), (33, 102), (60, 104)],
    "resp_rate": [(0, 15), (12, 15), (22, 24), (31, 24), (33, 27), (60, 27)],
    "spo2": [(0, 98), (12, 98), (22, 92), (31, 92), (33, 90), (60, 90)],
    "temp_c": [(0, 36.7), (31, 36.8), (33, 38.4), (60, 38.6)],
}
JOHN_SCRIPT = minute_script(JOHN_POINTS, 107, [0, 0, 3, 8],
                            "Trend alert by about minute 28, high NEWS2 8 alert by minute 45")
