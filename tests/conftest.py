"""Keeps tests off the real Sentry project: a DSN in .env must never receive test traffic."""
import dataclasses

import pytest

import backend.observability as observability
from backend.config import CONFIG, ObservabilityConfig


@pytest.fixture(autouse=True)
def sentry_stays_off_unless_a_test_asks(monkeypatch):
    off = dataclasses.replace(CONFIG, observability=ObservabilityConfig(dsn=""))
    monkeypatch.setattr(observability, "CONFIG", off)
