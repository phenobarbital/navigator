"""Shared pytest fixtures for geofencing tests."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from navigator.ext.geofencing.models import (
    Geofence,
    Position,
    GeofenceTransition,
    Webhook,
)
from navigator.ext.geofencing.engine import GeofenceEngine
from navigator.ext.geofencing.dispatcher import NotificationDispatcher


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

# Polygon around Mexico City (19.43, -99.13)
MEXICO_CITY_POLYGON_GEOJSON = json.dumps({
    "type": "Polygon",
    "coordinates": [[
        [-99.14, 19.42],
        [-99.12, 19.42],
        [-99.12, 19.44],
        [-99.14, 19.44],
        [-99.14, 19.42],
    ]],
})

# Point INSIDE the Mexico City polygon
INSIDE_LAT, INSIDE_LNG = 19.43, -99.13
# Point OUTSIDE the Mexico City polygon
OUTSIDE_LAT, OUTSIDE_LNG = 19.50, -99.20


# ---------------------------------------------------------------------------
# sample_tenant_geofences
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tenant_geofences() -> list[Geofence]:
    """Return a list with one geofence for tenant 'acme'.

    The polygon is a bounding box around Mexico City (19.43, -99.13).
    """
    return [
        Geofence(
            id=1,
            tenant_id="acme",
            name="mexico_city_office",
            polygon=MEXICO_CITY_POLYGON_GEOJSON,
            active=True,
            dwell_seconds=2,  # Short for tests
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
    ]


# ---------------------------------------------------------------------------
# fake_redis_dedup
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_dedup():
    """In-memory fake Redis for dedup tests.

    Returns a MagicMock whose ``set`` method simulates NX semantics:
    returns True on first call for a key, False on subsequent calls.
    """
    _store: dict[str, Any] = {}

    class _FakeRedis:
        async def set(self, name: str, value: str, ex: int = 0, nx: bool = False) -> bool:
            if nx and name in _store:
                return False
            _store[name] = value
            return True

        async def get(self, name: str):
            return _store.get(name)

        def clear(self):
            _store.clear()

    return _FakeRedis()


# ---------------------------------------------------------------------------
# sample_envelope_batch
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_envelope_batch() -> dict:
    """Return a valid MQTT location.batch envelope (camelCase as per bridge spec)."""
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


# ---------------------------------------------------------------------------
# mock_geofence_engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_geofence_engine(sample_tenant_geofences):
    """Return a real GeofenceEngine loaded with sample geofences.

    DB is mocked to return sample_tenant_geofences.
    """
    dispatched: list[GeofenceTransition] = []

    async def mock_emit(transition: GeofenceTransition) -> None:
        dispatched.append(transition)

    async def mock_db_loader() -> list[Geofence]:
        return sample_tenant_geofences

    engine = GeofenceEngine(
        db_loader=mock_db_loader,
        emit=mock_emit,
        dwell_default=2,  # 2s for fast tests
    )
    await engine.load_from_db()
    engine._dispatched = dispatched  # expose for assertions
    return engine


# ---------------------------------------------------------------------------
# mock_dispatcher
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_dispatcher():
    """Return a NotificationDispatcher with all external calls mocked."""
    mock_downlink = MagicMock()
    mock_downlink.publish_to_employee = AsyncMock()
    mock_publisher = MagicMock()
    mock_publisher.queue_event = AsyncMock()
    mock_fcm = MagicMock()
    mock_fcm.send = AsyncMock()

    async def mock_webhook_loader(transition):
        return []

    async def mock_device_tokens(employee_id):
        return []

    dispatcher = NotificationDispatcher(
        downlink=mock_downlink,
        internal_publisher=mock_publisher,
        fcm=mock_fcm,
        webhook_loader=mock_webhook_loader,
        webhook_decrypt=lambda b: b,
        device_token_lookup=mock_device_tokens,
    )
    yield dispatcher
    await dispatcher.aclose()
