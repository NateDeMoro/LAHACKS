import json
import logging
from datetime import UTC, datetime

import sentry_sdk

from backend.config import CONFIG
from backend.contracts import VitalsReading
from receiver.frames import FrameProcessor
from receiver.sender import QUEUE_MAX, IngestSender
from tests.receiver.test_frames import SEC, T0, FakeEstimator

CFG = CONFIG.receiver


def messages(caplog, text):
    return [r for r in caplog.records if text in r.getMessage()]


def frames(est=None):
    return FrameProcessor(CFG, est or FakeEstimator())


def test_contact_lost_and_regained_are_each_logged_once(caplog):
    proc = frames()
    with caplog.at_level(logging.INFO):
        proc.on_frame(T0, 70, [850], True)
        for i in range(1, 4):
            proc.on_frame(T0 + i * SEC, 0, [], False)
        proc.on_frame(T0 + 4 * SEC, 70, [850], True)
        proc.on_frame(T0 + 5 * SEC, 70, [850], True)
    assert len(messages(caplog, "contact lost")) == 1
    assert len(messages(caplog, "contact regained")) == 1
    assert messages(caplog, "contact lost")[0].wearable_id == CFG.wearable_id


def test_breathing_reason_is_logged_when_it_changes_not_every_second(caplog):
    class Reasons(FakeEstimator):
        def __init__(self, reasons):
            super().__init__()
            self.reasons, self.last_reason = iter(reasons), "ok"

        def estimate(self, now_s, contact=True):
            self.last_reason = next(self.reasons)
            return 15.0 if self.last_reason == "ok" else None

    proc = frames(Reasons(["few_beats", "few_beats", "few_beats", "ok", "ok", "gap"]))
    with caplog.at_level(logging.INFO):
        for i in range(6):
            proc.on_frame(T0 + i * SEC, 70, [850], True)
    reasons = [r.reason for r in messages(caplog, "breathing estimate")]
    assert reasons == ["few_beats", "ok", "gap"]


def reading(hr=70.0):
    return VitalsReading(wearable_id=1, ts=datetime(2026, 1, 1, tzinfo=UTC), hr=hr)


def test_a_slow_socket_counts_and_logs_dropped_readings(caplog):
    sender = IngestSender(CFG)
    sender.connected = True
    with caplog.at_level(logging.WARNING):
        for _ in range(QUEUE_MAX + 5):
            sender.send(reading())
    assert sender.dropped == 5
    assert len(messages(caplog, "dropping")) == 1  # the first drop; the next log comes at the eleventh


def test_a_message_carries_the_senders_trace_when_sentry_is_on(sentry):
    sender = IngestSender(CFG)
    sender.connected = True
    with sentry_sdk.start_transaction(op="receiver.reading", name="receiver reading") as txn:
        sender.send(reading())
    msg = json.loads(sender._queue[0])
    assert msg["sentry_trace"].startswith(txn.trace_id) and "baggage" in msg


def test_a_message_has_no_trace_fields_when_sentry_is_off():
    sender = IngestSender(CFG)
    sender.connected = True
    sender.send(reading())
    assert set(json.loads(sender._queue[0])) == {"type", "data"}
