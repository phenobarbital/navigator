"""Unit tests for @on_geofence_event decorator registry.

Coverage:
- test_decorator_registers_handler: decorated coroutine is in registry
- test_decorator_rejects_sync_fn: TypeError for non-coroutine
- test_decorator_filter_matching: handler matches correct transition fields
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from navigator.ext.geofencing.decorators import (
    on_geofence_event,
    get_matching_handlers,
    clear_registry,
    _REGISTRY,
)
from navigator.ext.geofencing.models import GeofenceTransition, Position


def _make_transition(
    kind="enter",
    employee_id="emp-001",
    tenant_id="acme",
    geofence_id=1,
) -> GeofenceTransition:
    return GeofenceTransition(
        employee_id=employee_id,
        geofence_id=geofence_id,
        tenant_id=tenant_id,
        kind=kind,
        location=Position(lat=19.43, lng=-99.13, ts=datetime.now(tz=timezone.utc)),
        ts=datetime.now(tz=timezone.utc),
        source_event_id=uuid.uuid4(),
        dwell_duration=None,
    )


@pytest.fixture(autouse=True)
def clear_handler_registry():
    """Clear the registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_decorator_registers_handler():
    """@on_geofence_event appends (filters, fn) to the registry."""

    @on_geofence_event(kind="enter")
    async def my_handler(transition):
        pass

    assert len(_REGISTRY) == 1
    filters, fn = _REGISTRY[0]
    assert filters["kind"] == "enter"
    assert fn is my_handler


def test_decorator_rejects_sync_fn():
    """@on_geofence_event raises TypeError for non-coroutine functions."""
    with pytest.raises(TypeError, match="coroutine function"):
        @on_geofence_event(kind="enter")
        def sync_handler(transition):
            pass


def test_decorator_filter_matching():
    """get_matching_handlers returns handlers whose filters match the transition."""

    @on_geofence_event(kind="enter", tenant_id="acme")
    async def enter_handler(t):
        pass

    @on_geofence_event(kind="exit")
    async def exit_handler(t):
        pass

    @on_geofence_event(kind="enter", tenant_id="other")
    async def other_handler(t):
        pass

    transition = _make_transition(kind="enter", tenant_id="acme")
    handlers = get_matching_handlers(transition)
    # Only enter_handler matches (other has wrong tenant, exit_handler has wrong kind)
    assert enter_handler in handlers
    assert exit_handler not in handlers
    assert other_handler not in handlers
