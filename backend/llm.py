"""One helper for asking StepFun (OpenAI-compatible) for JSON that matches a pydantic model.
Use when any component needs a structured LLM reply; only this file knows the provider.

Spike findings (B1, see notes/decisions.md): strict json_schema, json_object and no response_format all
return valid JSON; a call takes 25-45 s and spends 3-4.5k tokens, almost all reasoning, so max_tokens
must be generous; reasoning_effort="low" is needed or the reply can be cut off. Errors never include
the key, and messages sent to the model are never logged."""
import re
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

import sentry_sdk
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend.config import LlmConfig

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LlmError(Exception):
    pass


@dataclass
class LlmResult(Generic[T]):
    value: T
    retried: bool
    latency_s: float
    completion_tokens: int


def make_client(cfg: LlmConfig) -> OpenAI:
    if not cfg.api_key:
        raise LlmError("STEPFUN_API_KEY is empty: run with `uv run --env-file .env ...`")
    # max_retries=0: this module's single retry is the only retry
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, max_retries=0, timeout=cfg.timeout_s)


def _ask(client: OpenAI, cfg: LlmConfig, messages: list[dict], model_cls: type[BaseModel]):
    return client.chat.completions.create(
        model=cfg.model, messages=messages, temperature=cfg.temperature, max_tokens=cfg.max_tokens,
        reasoning_effort=cfg.reasoning_effort,
        response_format={"type": "json_schema", "json_schema": {
            "name": model_cls.__name__, "strict": True, "schema": model_cls.model_json_schema()}})


def json_completion(messages: list[dict], model_cls: type[T], cfg: LlmConfig | None = None,
                    client: OpenAI | None = None) -> LlmResult[T]:
    """Ask for JSON matching model_cls. On a parse or validation failure, retry once with the error
    fed back; a second failure, a cut-off reply or an API error raises LlmError."""
    with sentry_sdk.start_span(op="llm.json_completion", name=model_cls.__name__) as span:
        res = _json_completion(messages, model_cls, cfg, client)
        span.set_data("llm.retried", res.retried)  # the OpenAI span under this one has tokens per attempt
        span.set_data("llm.completion_tokens", res.completion_tokens)
        return res


def _json_completion(messages: list[dict], model_cls: type[T], cfg: LlmConfig | None,
                     client: OpenAI | None) -> LlmResult[T]:
    cfg = cfg or LlmConfig()
    client = client or make_client(cfg)
    start, retried, tokens = time.time(), False, 0
    msgs = list(messages)
    for attempt in range(2):
        try:
            resp = _ask(client, cfg, msgs, model_cls)
        except Exception as e:  # timeouts, rate limits, auth: surface the type only
            raise LlmError(f"StepFun call failed: {type(e).__name__}") from None
        choice = resp.choices[0]
        tokens += resp.usage.completion_tokens if resp.usage else 0
        if choice.finish_reason != "stop":
            raise LlmError(f"reply cut off (finish_reason={choice.finish_reason}); raise max_tokens")
        text = _FENCE.sub("", (choice.message.content or "").strip())
        try:
            return LlmResult(model_cls.model_validate_json(text), retried, time.time() - start, tokens)
        except ValidationError as e:
            if attempt == 1:
                raise LlmError(f"invalid reply after retry: {e.error_count()} validation errors") from None
            retried = True
            msgs = [*msgs, {"role": "assistant", "content": text},
                    {"role": "user", "content": f"That reply was invalid: {str(e)[:400]}\nReply again with JSON only."}]
    raise LlmError("unreachable")
