"""Sentry setup shared by the backend and the receiver. Use once at process start.
With no DSN Sentry stays off and every span call elsewhere is a no-op.
Patient text stays out: no PII, no prompts or replies on AI spans; log codes and ids, not typed strings."""
import logging

import sentry_sdk
from sentry_sdk.integrations.openai import OpenAIIntegration

from backend.config import CONFIG, ObservabilityConfig

log = logging.getLogger(__name__)

READING_OPS = {"receiver.reading", "ingest.reading", "ingest.tick"}


def _sampler(cfg: ObservabilityConfig):
    def sample(ctx: dict) -> float:
        parent = ctx.get("parent_sampled")
        if parent is not None:  # follow the receiver's decision so a trace is whole or absent
            return float(parent)
        op = ctx["transaction_context"].get("op")
        return cfg.reading_trace_rate if op in READING_OPS else cfg.trace_rate
    return sample


def _drop_access_log(log_item: dict, _hint: dict) -> dict | None:
    """Every request and socket would otherwise become a log line; the traces already show them."""
    return None if log_item.get("attributes", {}).get("logger.name") == "uvicorn.access" else log_item


def init_sentry(service: str, cfg: ObservabilityConfig | None = None) -> bool:
    cfg = cfg or CONFIG.observability
    if not cfg.dsn:
        log.info("SENTRY_DSN is empty: Sentry is off")
        return False
    sentry_sdk.init(
        dsn=cfg.dsn, environment=cfg.environment, traces_sampler=_sampler(cfg),
        profile_session_sample_rate=cfg.profile_rate, profile_lifecycle="trace",
        enable_logs=True, before_send_log=_drop_access_log, send_default_pii=False,
        integrations=[OpenAIIntegration(include_prompts=False)],
    )
    sentry_sdk.set_tag("service", service)
    return True


def trace_fields() -> dict[str, str]:
    """Trace headers for an outgoing WsMessage; empty when Sentry is off."""
    if not sentry_sdk.is_initialized():
        return {}
    return {"sentry_trace": sentry_sdk.get_traceparent(), "baggage": sentry_sdk.get_baggage()}
