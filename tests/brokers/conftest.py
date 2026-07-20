"""Shared pytest fixtures for broker tests."""
from __future__ import annotations

import uuid
from typing import Any

import pytest


@pytest.fixture
def fake_redis_dedup():
    """In-memory fake Redis with NX semantics for dedup tests."""
    _store: dict[str, Any] = {}

    class _FakeRedis:
        async def set(self, name: str, value: str = "1", ex: int = 0, nx: bool = False):
            """Mimic Redis SET NX: return True if set, None if key existed."""
            if nx and name in _store:
                return None  # Redis returns None when NX key already exists
            _store[name] = value
            return True

        async def get(self, name: str):
            return _store.get(name)

        def clear(self):
            _store.clear()

    return _FakeRedis()


@pytest.fixture
def sample_envelope_batch() -> dict:
    """Return a valid camelCase MQTT location.batch envelope."""
    return {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [
            {"lat": 19.43, "lng": -99.13, "ts": "2026-05-27T00:00:00Z"},
            {"lat": 19.43, "lng": -99.13, "ts": "2026-05-27T00:00:05Z"},
        ],
        "eventId": str(uuid.uuid4()),
    }
