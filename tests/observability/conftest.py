"""A Sentry client wired to an in-memory transport, so tests read back what would have been sent."""
import pytest
import sentry_sdk
from sentry_sdk.client import NonRecordingClient
from sentry_sdk.transport import Transport

from backend.config import ObservabilityConfig
from backend.observability import init_sentry


class Collector(Transport):
    def __init__(self):
        super().__init__()
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)

    def _items(self, kind):
        sentry_sdk.flush()
        return [i.payload.json for e in self.envelopes for i in e.items if i.type == kind]

    def transactions(self, name=None):
        txns = self._items("transaction")
        return [t for t in txns if name is None or t["transaction"] == name]

    def spans(self):
        """Every span sent, from transactions and from standalone span items, as (name, attributes/data)."""
        out = []
        for t in self.transactions():
            out += [(s.get("description") or s.get("op"), {"op": s.get("op"), **s.get("data", {})}) for s in t.get("spans", [])]
        for payload in self._items("span"):
            for s in payload["items"]:
                out.append((s["name"], {k: v["value"] for k, v in s.get("attributes", {}).items()}))
        return out

    def logs(self):
        return [{"body": it["body"], "level": it["level"],
                 **{k: v["value"] for k, v in it.get("attributes", {}).items()}}
                for payload in self._items("log") for it in payload["items"]]

    def text(self):
        """Everything sent, as one string, for checking that something never appears."""
        import json
        return json.dumps([self._items(k) for k in ("transaction", "span", "log", "event")], default=str)


@pytest.fixture
def sentry():
    transport = Collector()
    assert init_sentry("test", ObservabilityConfig(dsn="http://key@localhost/1", trace_rate=1.0, reading_trace_rate=1.0),
                       transport=transport)
    yield transport
    sentry_sdk.get_client().close()
    for scope in (sentry_sdk.get_global_scope(), sentry_sdk.get_isolation_scope(), sentry_sdk.get_current_scope()):
        scope.set_client(NonRecordingClient())  # back to Sentry off for the next test
