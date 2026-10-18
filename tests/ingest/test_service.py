import logging
from datetime import datetime, timedelta

from backend.config import IngestConfig
from backend.contracts import PatientRanges, VitalsReading
from backend.ingest.service import IngestService
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine
from backend.timeutil import LA

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=LA)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Out:
    """Stands in for the hub and the store: records what they are given."""

    def __init__(self):
        self.published, self.stored = [], []

    def publish(self, type_, model):
        self.published.append((type_, model))

    def write(self, kind, model, patient_id=None, source=None):
        self.stored.append((kind, model, source))

    def of(self, type_):
        return [m for t, m in self.published if t == type_]


def make(engine=None, cfg=None):
    clock, out = Clock(), Out()
    svc = IngestService(engine or RiskEngine(), AlertLogic(), out.publish, out, cfg or IngestConfig(), clock=clock)
    return svc, clock, out


def reading(**v):
    return VitalsReading(wearable_id=1, contact=True, **v)


def seconds(svc, clock, n, **vitals):
    for _ in range(n):
        clock.now += timedelta(seconds=1)
        svc.ingest(reading(**vitals), "strap")
        svc.tick()


def test_unassigned_wearable_is_dropped_and_logged(caplog):
    svc, clock, out = make(cfg=IngestConfig(default_assignments={}))
    with caplog.at_level(logging.WARNING):
        seconds(svc, clock, 3, hr=70, resp_rate=15)
    assert out.published == [] and out.stored == []
    assert caplog.text.count("unassigned") == 1  # logged once, not every second


def test_default_assignment_streams_i13_and_i14_each_second():
    svc, clock, out = make()
    seconds(svc, clock, 6, hr=70, resp_rate=15)
    live = out.of("I13")
    assert len(live) == 6 and live[-1].patient_id == "demo-001" and live[-1].hr == 70
    assert out.of("I14")[-1].news2 is not None


def test_assign_replaces_the_wearables_patient():
    svc, clock, out = make()
    svc.assign(1, "p-new")
    seconds(svc, clock, 1, hr=70)
    assert {w.patient_id for w in out.of("I13")} == {"p-new"}


def test_minute_close_feeds_engine_alerts_hub_and_store():
    svc, clock, out = make()
    svc.assign(1, "p1")
    svc.set_run_state("p1", "running")
    for _ in range(5 * 60):  # danger-level run long enough to pass the alert persistence window
        clock.now += timedelta(seconds=1)
        svc.ingest(reading(hr=140, resp_rate=30, spo2=90, temp_c=39.5), "simulator")
        svc.tick()
    assert len(out.of("I9")) >= 4 and out.of("I9")[-1].level == "danger"
    alerts = out.of("I10")
    assert alerts and alerts[0].patient_id == "p1"
    kinds = [k for k, _, _ in out.stored]
    assert kinds.count("I6") >= 4 and "I9" in kinds and "I10" in kinds
    assert "I1" in kinds


def test_last_minute_of_a_run_is_closed_when_the_run_ends():
    svc, clock, out = make()
    svc.assign(1, "p1")
    svc.set_run_state("p1", "running")
    for _ in range(100):
        clock.now += timedelta(seconds=1)
        svc.ingest(reading(hr=90, resp_rate=18, spo2=97, temp_c=37.0), "simulator")
        svc.tick()
    assert len(out.of("I9")) == 1
    svc.set_run_state("p1", "ended")
    assert len(out.of("I9")) == 2 and [k for k, _, _ in out.stored].count("I6") == 2


def test_strap_readings_dropped_in_run_mode_are_not_stored():
    svc, clock, out = make()
    svc.set_run_state("demo-001", "running")
    svc.ingest(reading(hr=70), "strap")
    svc.ingest(reading(hr=90), "simulator")
    assert [src for k, _, src in out.stored if k == "I1"] == ["simulator"]


def test_reassigning_wearables_never_leaves_a_dangling_mapping():
    svc, clock, out = make(cfg=IngestConfig(default_assignments={}))
    svc.assign(2, "p1")
    svc.assign(1, "p1")  # the patient moves to wearable 1
    svc.assign(2, "p2")
    seconds(svc, clock, 1, hr=70)  # wearable 1 still maps to p1; must not raise
    assert {w.patient_id for w in out.of("I13")} == {"p1", "p2"}


def test_dropped_patient_is_forgotten_by_the_hub():
    gone = []
    clock, out = Clock(), Out()
    svc = IngestService(RiskEngine(), AlertLogic(), out.publish, out, IngestConfig(), clock=clock, on_drop=gone.append)
    svc.assign(1, "p-new")
    assert gone == ["demo-001"]


def test_ranges_are_pushed_once_even_before_a_personal_baseline_exists():
    svc, clock, out = make()
    seconds(svc, clock, 130, hr=70, resp_rate=15)
    ranges = out.of("I8")
    assert len(ranges) == 1 and ranges[0].patient_id == "demo-001"


def test_engine_range_changes_are_pushed_as_i8():
    svc, _, out = make()
    svc.engine.ranges_listener(PatientRanges(patient_id="p1"))
    assert out.of("I8")[0].patient_id == "p1"


def test_engine_failure_does_not_stop_the_tick(caplog):
    class Broken(RiskEngine):
        def on_second(self, w):
            raise RuntimeError("boom")

    svc, clock, out = make(engine=Broken())
    with caplog.at_level(logging.ERROR):
        seconds(svc, clock, 2, hr=70)
    assert "boom" in caplog.text
    assert len(out.of("I13")) == 2  # the window still goes out


def test_trend_history_goes_to_the_engine_when_it_can_take_it():
    class Seedable(RiskEngine):
        seeded = None

        def seed_trend_history(self, patient_id, rows):
            self.seeded = (patient_id, rows)

    eng = Seedable()
    svc, _, _ = make(engine=eng)
    svc.seed_trend_history("p1", [1, 2])
    assert eng.seeded == ("p1", [1, 2])
    make()[0].seed_trend_history("p1", [1, 2])  # the real engine has no such method yet: no error
