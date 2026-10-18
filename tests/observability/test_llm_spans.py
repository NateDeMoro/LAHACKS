import json

import httpx
import pytest
import sentry_sdk
from openai import OpenAI
from pydantic import BaseModel

from backend.config import LlmConfig
from backend.llm import LlmError, json_completion

COMPLAINT = "PRIVATE-COMPLAINT-TEXT fever since monday"
REPLY = "PRIVATE-MODEL-REPLY"


class Reply(BaseModel):
    answer: str


def client(*contents: str) -> OpenAI:
    """An OpenAI client whose server answers with each content in turn."""
    queue = list(contents)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 1, "model": "step-5-preview",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": queue.pop(0)}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})

    return OpenAI(api_key="k", base_url="http://llm.test/v1", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def call(*contents, purpose=None):
    kw = {"purpose": purpose} if purpose else {}
    with sentry_sdk.start_transaction(op="t", name="t"):
        return json_completion([{"role": "user", "content": COMPLAINT}], Reply, LlmConfig(api_key="k"),
                               client(*contents), **kw)


def llm_span(sentry):
    return next(attrs for name, attrs in sentry.spans() if attrs.get("op") == "llm.json_completion")


def test_a_call_gets_a_labelled_span_with_tokens(sentry):
    call(json.dumps({"answer": "ok"}), purpose="adjuster")
    name = next(n for n, a in sentry.spans() if a.get("op") == "llm.json_completion")
    span = llm_span(sentry)
    assert name == "adjuster" and span["llm.purpose"] == "adjuster"
    assert span["llm.retried"] is False and span["llm.completion_tokens"] == 7


def test_without_a_purpose_the_reply_type_names_the_call(sentry):
    call(json.dumps({"answer": "ok"}))
    assert llm_span(sentry)["llm.purpose"] == "Reply"


def test_a_bad_first_reply_is_marked_retried(sentry):
    call("not json", json.dumps({"answer": "ok"}), purpose="adjuster")
    assert llm_span(sentry)["llm.retried"] is True


def test_the_openai_span_records_model_and_tokens(sentry):
    call(json.dumps({"answer": "ok"}))
    chat = next(attrs for name, attrs in sentry.spans() if attrs.get("gen_ai.operation.name") == "chat")
    assert chat["gen_ai.request.model"] == "step-5-preview"
    assert chat["gen_ai.usage.output_tokens"] == 7


def test_a_failed_call_still_leaves_a_span(sentry):
    with pytest.raises(LlmError):
        call("not json", "still not json", purpose="adjuster")
    assert llm_span(sentry)["llm.purpose"] == "adjuster"


def test_prompts_and_replies_are_never_sent(sentry):
    call(json.dumps({"answer": REPLY}), purpose="adjuster")
    assert COMPLAINT not in sentry.text() and REPLY not in sentry.text()


def test_error_events_carry_no_local_variables(sentry):
    def handler(complaint):  # the complaint is a local here, as it is in the real code
        raise ValueError("boom")

    try:
        handler(COMPLAINT)
    except ValueError:
        sentry_sdk.capture_exception()
    assert COMPLAINT not in sentry.text()
