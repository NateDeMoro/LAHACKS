"""The six scripted patients: two healthy, two at risk and two critical. Key values sit at
fractions 0, 0.3, 0.6 and 1 of the run; expect.news2 is checked against the real scorer in tests.
No profile has copd: the schema cannot express confirmed-COPD SpO2 targets."""
from backend.contracts import IntakeRecord, Triage
from backend.simulator.models import KEY_FRACTIONS, Expect, Glitch, Keyframe, Profile, RunScript, Track

_WOBBLE_STEP = {"hr": (2, 1), "resp_rate": (1, 1), "spo2": (0.8, 1), "temp_c": (0.05, 0.1)}


def _script(hr, resp_rate, spo2, temp_c, seed, news2, alerts, glitches=()) -> RunScript:
    values = {"hr": hr, "resp_rate": resp_rate, "spo2": spo2, "temp_c": temp_c}
    tracks = {
        v: Track(keyframes=[Keyframe(at=a, value=x) for a, x in zip(KEY_FRACTIONS, vals)],
                 wobble=_WOBBLE_STEP[v][0], step=_WOBBLE_STEP[v][1])
        for v, vals in values.items()
    }
    return RunScript(tracks=tracks, glitches=list(glitches), seed=seed,
                     expect=Expect(news2=news2, alerts=alerts))


def _profile(id, name, tier, age, sex, height_cm, weight_kg, conditions, medications, complaint,
             sbp, dbp, alertness, pain, on_oxygen, level, script) -> Profile:
    id = id.lower()  # ids appear in URLs and I12 scenario ids
    record = IntakeRecord(
        patient_id=f"sim-{id}", arrival_ts=None,  # the nurse picks the wearable at intake
        age=age, sex=sex, height_cm=height_cm, weight_kg=weight_kg, pregnant=False,
        conditions=conditions, medications=medications, chief_complaint=complaint,
        triage=Triage(sbp=sbp, dbp=dbp, alertness=alertness, pain=pain, on_oxygen=on_oxygen, level=level),
    )
    return Profile(id=id, name=name, tier=tier, record=record, script=script)


_LIST = [
    _profile(
        "H1", "Ankle sprain", "healthy", 24, "male", 178, 72, [], [],
        "Rolled my ankle playing soccer, can't put weight on it.",
        118, 74, "alert", 5, False, 4,
        _script([72, 74, 73, 72], [14, 14, 15, 14], [98] * 4, [36.6] * 4, 101, [0, 0, 0, 0],
                "None: the 8 s SpO2 dip is absorbed by the 60-second median",
                glitches=[Glitch(vital="spo2", at=0.5, duration_s=8, value=90)]),
    ),
    _profile(
        "H2", "Sore throat", "healthy", 41, "female", 165, 63, [], [],
        "Sore throat and a mild cough for three days.",
        112, 70, "alert", 2, False, 5,
        _script([78, 78, 105, 80], [15, 15, 22, 16], [97, 97, 96, 97], [36.8] * 4, 102, [0, 0, 3, 0],
                "None: warning at most, then clears"),
    ),
    _profile(
        "U1", "Fever on a beta-blocker", "at_risk", 67, "male", 172, 94,
        ["hypertension", "diabetes"], ["metoprolol", "lisinopril", "metformin"],
        "Fever and chills for two days, barely eating, feel weak.",
        128, 80, "alert", 3, False, 3,
        _script([82, 88, 98, 104], [18, 20, 23, 26], [95, 94, 93, 92], [37.8, 38.2, 38.7, 39.2], 103,
                [1, 2, 6, 8], "Urgent between 3 and 6 minutes, high near the end"),
    ),
    _profile(
        "U2", "Asthma flare", "at_risk", 31, "female", 168, 82, ["asthma"], ["albuterol inhaler"],
        "Wheezing since last night, inhaler isn't helping as much.",
        122, 78, "alert", 1, False, 3,
        _script([96, 104, 114, 120], [20, 24, 27, 28], [95, 94, 92, 91], [36.9] * 4, 104,
                [2, 4, 7, 8], "Urgent after 3 minutes, high by about 6 minutes"),
    ),
    _profile(
        "C1", "Heart failure, short of breath", "critical", 72, "male", 175, 88,
        ["heart_failure", "hypertension"], ["carvedilol", "furosemide", "lisinopril"],
        "Short of breath, can't lie flat, legs swollen, worse over three days.",
        104, 66, "alert", 2, True, 2,
        _script([88, 90, 112, 134], [20, 20, 25, 30], [95, 94, 92, 89], [36.8] * 4, 105,
                [4, 4, 10, 12], "Below urgent (4) for about 3 minutes, then high (7+) from about minute 4 and 10+ by minute 7"),
    ),
    _profile(
        "C2", "Septic-looking, confused", "critical", 58, "female", 160, 70,
        ["diabetes", "cancer"], ["capecitabine", "metformin"],
        "Fever, shaking chills, confused since this morning, family says she isn't making sense.",
        92, 58, "new_confusion", 0, False, 2,
        _script([96, 108, 122, 136], [20, 23, 26, 30], [96, 95, 93, 92], [38.6, 38.9, 39.2, 39.5], 106,
                [7, 10, 14, 15], "High from the first minute"),
    ),
]
PROFILES: dict[str, Profile] = {p.id: p for p in _LIST}
