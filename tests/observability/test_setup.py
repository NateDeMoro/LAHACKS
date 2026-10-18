import sentry_sdk

from backend.config import ObservabilityConfig
from backend.observability import _sampler, init_sentry, trace_fields


def test_without_a_dsn_sentry_stays_off():
    assert init_sentry("test", ObservabilityConfig(dsn="")) is False
    assert not sentry_sdk.is_initialized()
    assert trace_fields() == {}


def test_trace_fields_carry_the_current_trace(sentry):
    with sentry_sdk.start_transaction(op="t", name="t"):
        fields = trace_fields()
    assert set(fields) == {"sentry_trace", "baggage"} and fields["sentry_trace"]


def test_service_is_tagged(sentry):
    with sentry_sdk.start_transaction(op="t", name="t"):
        pass
    assert sentry.transactions("t")[0]["tags"]["service"] == "test"


def test_readings_are_sampled_and_everything_else_is_kept():
    cfg = ObservabilityConfig(dsn="x", reading_trace_rate=0.1, trace_rate=1.0)
    sample = _sampler(cfg)
    for op in ("receiver.reading", "ingest.reading", "ingest.tick"):
        assert sample({"transaction_context": {"op": op}}) == 0.1
    for op in ("engine.period", "intake.adjust", "http.server"):
        assert sample({"transaction_context": {"op": op}}) == 1.0


def test_a_senders_sampling_decision_wins():
    sample = _sampler(ObservabilityConfig(dsn="x", reading_trace_rate=0.1))
    assert sample({"transaction_context": {"op": "ingest.reading"}, "parent_sampled": True}) == 1.0
    assert sample({"transaction_context": {"op": "ingest.reading"}, "parent_sampled": False}) == 0.0


def test_a_message_sent_outside_any_transaction_carries_no_trace(sentry):
    # The no-strap heartbeat is sent this way; sharing one trace id for the whole process would pile them into one trace.
    assert trace_fields() == {}


def test_error_messages_do_not_carry_what_the_user_typed(sentry):
    from backend.contracts import IntakeRecord
    secret = "PRIVATE-" + "COMPLAINT-TEXT"  # built here so the test's own source line does not contain it
    try:
        IntakeRecord(age=secret)
    except Exception:
        sentry_sdk.capture_exception()
    assert secret not in sentry.text()
    assert "ValidationError" in sentry.text()  # the type is still there to debug with


def test_automatic_collection_is_off_beyond_the_ai_fields(sentry):
    dc = sentry_sdk.get_client().options["data_collection"]
    assert dc["cookies"]["mode"] == "off" and dc["url_query_params"]["mode"] == "off"
    assert dc["database_query_data"] is False and dc["queues"] is False and dc["user_info"] is False


def test_a_dsn_in_the_environment_does_not_reach_the_tests():
    assert init_sentry("test") is False  # the autouse fixture in tests/conftest.py blanks the DSN
