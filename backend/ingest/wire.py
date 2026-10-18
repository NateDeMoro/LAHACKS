"""Parses one WebSocket text message into an interface model. Shared by /ws/ingest and the dashboard hub."""
import json
import math

from pydantic import ValidationError

from backend.contracts import INTERFACES, Model, WsMessage


class BadMessage(ValueError):
    pass


def _finite(s: str) -> float | None:
    v = float(s)
    return v if math.isfinite(v) else None


def trace_headers(text: str) -> dict[str, str]:
    """Sentry headers a sender put in the envelope. Looks for the key first so most messages skip a second parse."""
    if '"sentry_trace"' not in text:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        return {}
    return {k: v for k, v in (("sentry-trace", raw.get("sentry_trace")), ("baggage", raw.get("baggage"))) if v}


def parse_envelope(text: str, allowed: set[str]) -> tuple[str, Model]:
    """A non-finite number becomes null so the rest of the reading survives (component-map: treat as null)."""
    try:
        raw = json.loads(text, parse_constant=lambda _: None, parse_float=_finite)
        msg = WsMessage(**raw)
    except (ValueError, TypeError, ValidationError) as e:
        raise BadMessage(f"not a valid envelope: {type(e).__name__}") from None
    if msg.type not in allowed or msg.data is None:
        raise BadMessage(f"type {msg.type!r} not accepted here")
    try:
        return msg.type, INTERFACES[msg.type](**msg.data)
    except ValidationError as e:
        fields = ", ".join(".".join(map(str, err["loc"])) for err in e.errors())
        raise BadMessage(f"{msg.type} invalid: {fields}") from None
