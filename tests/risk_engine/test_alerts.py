import logging
from datetime import timedelta

from backend.contracts import Acknowledgment, AlertConfig, News2Points, RiskResult, VitalLevels, VitalValues
from backend.risk_engine.alerts import AlertLogic
from tests.risk_engine.risk_helpers import T0

PID = "p"


def cfg(**kw):
    base = dict(warning_persisted_minutes=5, vital_danger_minutes=2, news2_total_minutes=2,
                trend_minutes=5, max_gap_minutes=10, clear_minutes=5, ack_cooldown_minutes=15)
    return AlertConfig(**{**base, **kw})


def logic(**kw):
    return AlertLogic(cfg(**kw), bed_label=lambda pid: "Bed 4")


def row(i, rr=None, hr=None, news2=None, pts=None, tier=None, reason=None, level=None):
    """One I9 at minute i. rr/hr are level strings ('safe'|'warning'|'danger') or None for a missing vital."""
    vals = {"resp_rate": {"warning": 22, "danger": 26}.get(rr, 16 if rr else None),
            "hr": {"warning": 105, "danger": 135}.get(hr, 70 if hr else None)}
    return RiskResult(
        patient_id=PID, ts=T0 + timedelta(minutes=i), level=level,
        vital_levels=VitalLevels(resp_rate=rr, hr=hr), vital_values=VitalValues(**vals),
        news2=news2, news2_points=pts, trend_tier=tier, trend_reason_fast=reason)


def feed(lg, rows):
    out = []
    for r in rows:
        out += lg.on_risk(r)
    return out


def ack(alert, minutes):
    return Acknowledgment(alert_id=alert.alert_id, ts=T0 + timedelta(minutes=minutes))


def ids(events):
    return [(e.trigger, e.severity, e.vital, e.resolved) for e in events]


# ---- persistence and severity ------------------------------------------------------------------
def test_warning_fires_after_window_not_before():
    lg = logic()
    assert feed(lg, [row(i, rr="warning") for i in range(5)]) == []  # held 4 min
    ev = lg.on_risk(row(5, rr="warning"))
    assert ids(ev) == [("warning_persisted", "warning", "resp_rate", False)]
    assert ev[0].supersedes == [] and ev[0].alert_id == "p|resp_rate|" + (T0 + timedelta(minutes=5)).isoformat()


def test_window_zero_fires_immediately():
    ev = logic(warning_persisted_minutes=0).on_risk(row(0, rr="warning"))
    assert ids(ev) == [("warning_persisted", "warning", "resp_rate", False)]


def test_interrupted_run_restarts():
    lg = logic()
    feed(lg, [row(0, rr="warning"), row(3, rr="warning"), row(4, rr="safe")])
    assert feed(lg, [row(5, rr="warning"), row(9, rr="warning")]) == []  # run restarted at 5
    assert len(lg.on_risk(row(10, rr="warning"))) == 1


def test_null_minute_neither_counts_nor_breaks():
    lg = logic()
    feed(lg, [row(0, rr="warning"), row(1, rr=None), row(2, rr=None)])  # missing vital
    assert feed(lg, [row(4, rr="warning")]) == []
    assert len(lg.on_risk(row(5, rr="warning"))) == 1  # counted from minute 0


def test_long_gap_resets_run():
    lg = logic()
    feed(lg, [row(0, rr="warning")])
    assert lg.on_risk(row(12, rr="warning")) == []  # 12 min gap > 10: run restarts at 12
    assert lg.on_risk(row(16, rr="warning")) == []
    assert len(lg.on_risk(row(17, rr="warning"))) == 1


def test_severity_mapping_and_warning_to_danger_supersedes():
    lg = logic()
    warn = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    ev = feed(lg, [row(6, rr="danger"), row(7, rr="danger"), row(8, rr="danger")])
    assert ids(ev) == [("vital_danger", "urgent", "resp_rate", False)]
    assert ev[0].supersedes == [warn.alert_id]


def test_danger_from_idle_fires_urgent_after_its_window():
    ev = feed(logic(), [row(0, rr="danger"), row(1, rr="danger"), row(2, rr="danger")])
    assert ids(ev) == [("vital_danger", "urgent", "resp_rate", False)]


def test_news2_severity_urgent_then_high():
    lg = logic()
    ev = feed(lg, [row(i, news2=5) for i in range(3)])
    assert ids(ev) == [("news2_total", "urgent", None, False)]
    ev2 = feed(lg, [row(3, news2=7), row(4, news2=7), row(5, news2=8)])
    assert ids(ev2) == [("news2_total", "high", None, False)] and ev2[0].supersedes == [ev[0].alert_id]


def test_trend_warning():
    ev = feed(logic(), [row(i, tier="warning", reason="SpO2 falling") for i in range(6)])
    assert ids(ev) == [("trend", "warning", None, False)]
    assert ev[0].message == "Bed 4: may reach danger soon (SpO2 falling)"


# ---- state table -------------------------------------------------------------------------------
def test_open_rise_and_no_duplicate_while_holding():
    lg = logic()
    first = feed(lg, [row(i, rr="warning") for i in range(6)])
    assert len(first) == 1
    assert feed(lg, [row(i, rr="warning") for i in range(6, 30)]) == []  # one alert per problem


def test_open_clear_sends_resolved_update_then_stays():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    ev = feed(lg, [row(i, rr="safe") for i in range(6, 11)])
    assert ev == []  # clear for 4 min
    ev = lg.on_risk(row(11, rr="safe"))
    assert len(ev) == 1 and ev[0].alert_id == a.alert_id and ev[0].resolved is True
    assert feed(lg, [row(i, rr="safe") for i in range(12, 30)]) == []  # nothing more until acknowledged
    assert lg.on_ack(ack(a, 40)) is True


def test_resolved_alert_then_problem_returns_supersedes_it():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    feed(lg, [row(i, rr="safe") for i in range(6, 12)])
    ev = feed(lg, [row(i, rr="warning") for i in range(12, 18)])
    assert len(ev) == 1 and ev[0].supersedes == [a.alert_id] and ev[0].resolved is False


def test_acknowledged_quiet_until_cooldown_then_refires_without_new_window():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]  # fired at 5
    assert lg.on_ack(ack(a, 6))
    assert feed(lg, [row(i, rr="warning") for i in range(7, 21)]) == []  # cooldown ends at 21
    ev = lg.on_risk(row(21, rr="warning"))
    assert ids(ev) == [("warning_persisted", "warning", "resp_rate", False)]
    assert ev[0].supersedes == [a.alert_id]


def test_acknowledged_rise_above_acknowledged_severity_refires():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    lg.on_ack(ack(a, 6))
    ev = feed(lg, [row(i, rr="danger") for i in range(7, 10)])
    assert ids(ev) == [("vital_danger", "urgent", "resp_rate", False)] and ev[0].supersedes == [a.alert_id]


def test_acknowledged_same_severity_does_not_refire_before_cooldown():
    lg = logic()
    a = feed(lg, [row(i, rr="danger") for i in range(3)])[0]
    lg.on_ack(ack(a, 3))
    assert feed(lg, [row(i, rr="danger") for i in range(3, 15)]) == []


def test_acknowledged_clear_goes_idle_and_new_problem_needs_new_window():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    lg.on_ack(ack(a, 6))
    assert feed(lg, [row(i, rr="safe") for i in range(7, 13)]) == []  # clear 5 min -> idle, no event
    assert feed(lg, [row(i, rr="warning") for i in range(13, 18)]) == []  # new window running
    ev = lg.on_risk(row(18, rr="warning"))
    assert len(ev) == 1 and ev[0].supersedes == []  # fresh alert, not a supersede


def test_ack_of_resolved_alert_goes_idle_on_next_clear_observation():
    lg = logic()
    a = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    feed(lg, [row(i, rr="safe") for i in range(6, 12)])  # resolved at 11
    assert lg.on_ack(ack(a, 12))
    assert feed(lg, [row(13, rr="safe")]) == []
    assert feed(lg, [row(i, rr="warning") for i in range(14, 19)]) == []  # idle: needs a fresh window
    assert len(lg.on_risk(row(19, rr="warning"))) == 1


def test_ack_of_older_alert_in_chain_acks_head():
    lg = logic()
    warn = feed(lg, [row(i, rr="warning") for i in range(6)])[0]
    urgent = feed(lg, [row(i, rr="danger") for i in range(6, 9)])[0]
    assert lg.on_ack(ack(warn, 9)) is True  # acks the urgent head
    assert feed(lg, [row(i, rr="danger") for i in range(10, 24)]) == []  # quiet through the cooldown
    assert lg.on_ack(ack(urgent, 25)) is False  # already acknowledged


def test_unknown_ack_logged_and_ignored(caplog):
    lg = logic()
    with caplog.at_level(logging.WARNING):
        assert lg.on_ack(Acknowledgment(alert_id="nope", ts=T0)) is False
    assert "unknown alert" in caplog.text


# ---- NEWS2 folding -----------------------------------------------------------------------------
def test_news2_supersedes_open_vital_alerts_and_holds_vitals_after_ack():
    lg = logic()
    vit = feed(lg, [row(i, rr="warning", hr="warning") for i in range(6)])
    assert {e.vital for e in vit} == {"resp_rate", "hr"}
    ev = feed(lg, [row(i, rr="danger", hr="warning", news2=6) for i in range(6, 9)])
    n2 = [e for e in ev if e.trigger == "news2_total"]
    assert len(n2) == 1 and sorted(n2[0].supersedes) == sorted(e.alert_id for e in vit)
    assert [e for e in ev if e.trigger == "vital_danger"] == []  # the vital stays folded
    lg.on_ack(ack(n2[0], 9))
    held = feed(lg, [row(i, rr="danger", hr="danger", news2=6) for i in range(10, 24)])
    assert [e for e in held if e.vital] == []  # still folded after acknowledgment
    # ack of a folded vital alert reaches the NEWS2 head (it was acked above, so nothing changes)
    assert lg.on_ack(ack(vit[0], 24)) is False


def test_news2_release_fires_still_holding_vital_at_once():
    lg = logic()
    ev = feed(lg, [row(i, rr="warning", news2=5) for i in range(3)])
    n2 = ev[0]
    assert [e.vital for e in ev] == [None]  # the vital's own 5 min window had not run
    lg.on_ack(ack(n2, 3))
    # news2 drops below 5; after 5 clear minutes the key is idle again and the vital (holding) fires at once
    out = feed(lg, [row(i, rr="warning", news2=2) for i in range(4, 9)])
    assert out == []
    ev = lg.on_risk(row(9, rr="warning", news2=2))
    assert ids(ev) == [("warning_persisted", "warning", "resp_rate", False)]


def test_news2_release_does_not_fire_vital_that_cleared():
    lg = logic()
    n2 = feed(lg, [row(i, rr="warning", news2=5) for i in range(3)])[0]
    lg.on_ack(ack(n2, 3))
    out = feed(lg, [row(i, rr="safe", news2=2) for i in range(4, 12)])
    assert out == []


def test_news2_resolved_update_releases_folding():
    lg = logic()
    n2 = feed(lg, [row(i, rr="danger", news2=6) for i in range(3)])[0]
    out = feed(lg, [row(i, rr="danger", news2=2) for i in range(3, 9)])
    assert [(e.trigger, e.resolved) for e in out] == [("news2_total", True), ("vital_danger", False)]
    assert out[0].alert_id == n2.alert_id


def test_news2_null_does_not_break_hold():
    lg = logic()
    feed(lg, [row(0, news2=5), row(1, news2=None), row(2, news2=5)])
    # fired at minute 2 (held since 0)
    assert lg._keys[PID]["news2"].state == "open"


def test_never_two_open_alerts_for_a_key():
    lg = logic(warning_persisted_minutes=0, vital_danger_minutes=0, news2_total_minutes=0)
    live = {}
    levels = ["warning", "danger", "warning", "safe", "danger", "danger", "safe", "warning"] * 6
    for i, lv in enumerate(levels):
        for e in lg.on_risk(row(i, rr=lv, news2=6 if lv == "danger" else 1)):
            key = e.alert_id.split("|")[1]
            if e.resolved:
                continue
            for s in e.supersedes:
                live.pop(s, None)
            assert key not in {k.split("|")[1] for k in live}
            live[e.alert_id] = e
        if i % 5 == 4 and live:
            lg.on_ack(ack(list(live.values())[0], i))


# ---- messages ----------------------------------------------------------------------------------
def test_vital_message_with_points_and_stale_points_left_out():
    pts = News2Points(resp_rate=3, hr=0)
    ev = logic(warning_persisted_minutes=0).on_risk(row(0, rr="danger", news2=3, pts=pts))
    assert ev[0].message == "Bed 4: breathing 26/min, 3 points"
    ev = logic(warning_persisted_minutes=0).on_risk(row(0, rr="warning"))  # news2_points null: stale
    assert ev[0].message == "Bed 4: breathing 22/min"


def test_news2_message_names_drivers():
    pts = News2Points(resp_rate=3, hr=2, spo2=1)
    ev = logic(news2_total_minutes=0).on_risk(row(0, news2=6, pts=pts))
    assert ev[0].message == "Bed 4: NEWS2 6 (breathing, heart rate)"
    ev = logic(news2_total_minutes=0).on_risk(row(0, news2=6))  # stale points
    assert ev[0].message == "Bed 4: NEWS2 6"


def test_bed_lookup_and_fallback():
    r = row(0, rr="warning")
    quiet = cfg(warning_persisted_minutes=0)
    assert AlertLogic(quiet).on_risk(r)[0].message.startswith("p: ")  # no lookup: patient_id
    assert AlertLogic(quiet, bed_label=lambda pid: None).on_risk(r)[0].message.startswith("p: ")

    def boom(pid):
        raise KeyError(pid)
    assert AlertLogic(quiet, bed_label=boom).on_risk(r)[0].message.startswith("p: ")
