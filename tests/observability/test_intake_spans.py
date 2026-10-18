import asyncio
import json
import logging

import sentry_sdk

from backend.adjuster import adjuster as A
from backend.config import AdjusterConfig
from backend.contracts import IntakeRecord, PatientContext
from backend.intake.service import IntakeService
from backend.risk_engine.engine import RiskEngine
from tests.observability.test_llm_spans import COMPLAINT, client

ADJ = AdjusterConfig(use_cache=False, write_log=False)


def test_the_adjusters_model_call_is_labelled(sentry):
    ctx = PatientContext(patient_id="p", age=40, chief_complaint=COMPLAINT)
    with sentry_sdk.start_transaction(op="t", name="t"):
        A.adjust(ctx, client=client(json.dumps({"proposals": []})), adj=ADJ)
    assert any(a.get("llm.purpose") == "adjuster" for _, a in sentry.spans())


def service(adjust_fn):
    return IntakeService(RiskEngine(), lambda a: None, adjust_fn=adjust_fn)


def record(complaint):
    return IntakeRecord(patient_id="p1", wearable_id=1, age=40, sex="female", chief_complaint=complaint)


def outcome(ctx, llm_ok, latency):
    out = A.adjust_structured(ctx)
    out.llm_ok, out.latency_s = llm_ok, latency
    return out


async def submit_and_settle(svc, rec):
    with sentry_sdk.start_transaction(op="http.server", name="POST /intake") as request:
        await svc.submit(rec)
    await asyncio.gather(*svc._tasks)
    return request


def test_the_background_adjuster_joins_the_intake_trace(sentry):
    svc = service(lambda ctx: outcome(ctx, True, 0.0))
    request = asyncio.run(submit_and_settle(svc, record(COMPLAINT)))
    adjust = sentry.transactions("intake adjust")[0]
    assert adjust["contexts"]["trace"]["trace_id"] == request.trace_id
    data = adjust["contexts"]["trace"]["data"]
    assert data["adjuster.llm_ok"] is True and data["adjuster.cache_hit"] is True and data["adjuster.dropped"] == 0


def test_a_live_model_call_is_not_a_cache_hit(sentry):
    svc = service(lambda ctx: outcome(ctx, True, 31.5))
    asyncio.run(submit_and_settle(svc, record(COMPLAINT)))
    assert sentry.transactions("intake adjust")[0]["contexts"]["trace"]["data"]["adjuster.cache_hit"] is False


def test_falling_back_to_rules_is_logged_without_the_complaint(sentry, caplog):
    svc = service(lambda ctx: outcome(ctx, False, 0.0))
    with caplog.at_level(logging.WARNING):
        asyncio.run(submit_and_settle(svc, record(COMPLAINT)))
    logs = [l for l in sentry.logs() if "fell back" in l["body"]]
    assert logs and logs[0]["patient_id"] == "p1"
    assert COMPLAINT not in sentry.text()


def test_no_complaint_means_no_fallback_log(sentry):
    svc = service(lambda ctx: outcome(ctx, False, 0.0))
    asyncio.run(submit_and_settle(svc, record("")))
    assert not [l for l in sentry.logs() if "fell back" in l["body"]]


def test_the_background_task_leaves_the_request_trace_alone(sentry):
    import time
    svc = service(lambda ctx: (time.sleep(0.2), outcome(ctx, True, 1.0))[1])

    async def go():
        with sentry_sdk.start_transaction(op="http.server", name="POST /intake") as request:
            await svc.submit(record(COMPLAINT))
            await asyncio.sleep(0.05)  # the adjuster task is now running in its own transaction
            assert sentry_sdk.get_current_span() is request
        await asyncio.gather(*svc._tasks)

    asyncio.run(go())
