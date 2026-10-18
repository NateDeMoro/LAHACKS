import pytest

from backend.contracts import Acknowledgment, VitalsReading
from backend.ingest.wire import BadMessage, parse_envelope


def test_valid_message_returns_type_and_model():
    t, m = parse_envelope('{"type":"I1","data":{"wearable_id":1,"hr":72}}', {"I1"})
    assert t == "I1" and isinstance(m, VitalsReading) and m.hr == 72


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_field_becomes_null_and_rest_is_kept(bad):
    _, m = parse_envelope('{"type":"I1","data":{"wearable_id":1,"hr":72,"spo2":%s}}' % bad, {"I1"})
    assert m.spo2 is None and m.hr == 72


@pytest.mark.parametrize("text", [
    "not json",
    '{"type":"I1"}',
    '{"type":"I9","data":{}}',  # known interface but not allowed here
    '{"type":"I99","data":{}}',
    '{"type":"I1","data":{"bogus":1}}',  # unknown field
    '{"type":"I1","data":{"ts":"2026-10-18T09:00:00"}}',  # naive timestamp
    '[1,2]',
])
def test_bad_messages_raise_bad_message(text):
    with pytest.raises(BadMessage):
        parse_envelope(text, {"I1"})


def test_allowed_set_selects_the_model():
    t, m = parse_envelope('{"type":"I11","data":{"alert_id":"a"}}', {"I11", "I12"})
    assert t == "I11" and isinstance(m, Acknowledgment)
