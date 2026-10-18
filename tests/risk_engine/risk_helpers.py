from datetime import datetime, timedelta, timezone

from backend.contracts import PeriodSummary, PatientContext

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone(timedelta(hours=-7)))


def period(i, hr=None, rr=None, clean=None, pid="p"):
    return PeriodSummary(patient_id=pid, period_ts=T0 + timedelta(minutes=i), hr=hr, resp_rate=rr,
                         clean_seconds=clean)


def ctx(**kw):
    return PatientContext(patient_id="p", age=50, sex="male", height_cm=175, weight_kg=80, **kw)
