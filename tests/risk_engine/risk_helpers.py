from datetime import datetime, timedelta, timezone

from backend.contracts import MinuteSummary, PatientContext

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone(timedelta(hours=-7)))


def minute(i, hr=None, rr=None, clean=None, pid="p"):
    return MinuteSummary(patient_id=pid, minute_ts=T0 + timedelta(minutes=i), hr=hr, resp_rate=rr,
                         clean_seconds=clean)


def ctx(**kw):
    return PatientContext(patient_id="p", age=50, sex="male", height_cm=175, weight_kg=80, **kw)
