import pytest

from backend.risk_engine import news2
from backend.simulator.generate import keyframe_sample
from backend.simulator.models import KEY_FRACTIONS
from backend.simulator.profiles import PROFILES


@pytest.mark.parametrize("pid", list(PROFILES))
def test_expected_news2_matches_scorer(pid):
    p = PROFILES[pid]
    t = p.record.triage
    totals = []
    for at in KEY_FRACTIONS:
        s = keyframe_sample(p.script, at)
        total, _ = news2.score(resp_rate=s.resp_rate, spo2=s.spo2, on_oxygen=t.on_oxygen,
                               sbp=t.sbp, hr=s.hr, alertness=t.alertness, temp_c=s.temp_c)
        totals.append(total)
    assert totals == p.script.expect.news2


def test_profile_records_are_usable():
    for pid, p in PROFILES.items():
        assert "copd" not in (p.record.conditions or [])
        t = p.record.triage
        assert None not in (t.sbp, t.alertness, t.on_oxygen), pid
