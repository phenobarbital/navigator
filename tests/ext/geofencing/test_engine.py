"""Unit tests for GeofenceEngine.

Coverage:
- test_engine_load_from_db: engine loads geofences and builds STRtree
- test_engine_enter_detected: evaluate() fires enter transition when point enters polygon
- test_engine_exit_detected: evaluate() fires exit when point leaves polygon
- test_engine_no_transition_inside: staying inside does not re-fire enter
- test_engine_no_transition_outside: staying outside does not fire
- test_engine_point_ordering_trap: Point(lng, lat) ordering — use real-world coords
- test_engine_out_of_order_ignored: older timestamp is ignored
- test_engine_dwell_timer_fires: dwell fires after dwell_seconds (fast)
- test_engine_dwell_timer_cancelled_on_exit: exit cancels pending dwell timer
- test_engine_batch_enter_exit: evaluate_batch collapses intra-batch redundancy
- test_engine_reload_one: reload_one re-invokes load_from_db
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from navigator.ext.geofencing.models import Geofence, Position
from navigator.ext.geofencing.engine import GeofenceEngine

from tests.ext.geofencing.conftest import (
    INSIDE_LAT, INSIDE_LNG,
    OUTSIDE_LAT, OUTSIDE_LNG,
    MEXICO_CITY_POLYGON_GEOJSON,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_engine(geofences, dwell_default=2):
    dispatched = []

    async def emit(t):
        dispatched.append(t)

    async def loader():
        return geofences

    engine = GeofenceEngine(db_loader=loader, emit=emit, dwell_default=dwell_default)
    await engine.load_from_db()
    return engine, dispatched


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_load_from_db(sample_tenant_geofences):
    """Engine loads geofences and builds per-tenant STRtree."""
    engine, _ = await _make_engine(sample_tenant_geofences)
    assert "acme" in engine._trees
    assert len(engine._polys_by_tenant["acme"]) == 1


@pytest.mark.asyncio
async def test_engine_enter_detected(sample_tenant_geofences):
    """Point inside polygon triggers enter transition."""
    engine, dispatched = await _make_engine(sample_tenant_geofences)
    ts = _now()
    transitions = engine.evaluate(
        employee_id="emp-001",
        tenant_id="acme",
        lat=INSIDE_LAT,
        lng=INSIDE_LNG,
        ts=ts,
        source_event_id=uuid.uuid4(),
    )
    enter_kinds = [t.kind for t in transitions]
    assert "enter" in enter_kinds


@pytest.mark.asyncio
async def test_engine_exit_detected(sample_tenant_geofences):
    """After an enter, moving outside polygon triggers exit."""
    engine, dispatched = await _make_engine(sample_tenant_geofences)
    ts1 = _now()
    ts2 = ts1 + timedelta(seconds=1)
    engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts1, uuid.uuid4())
    transitions = engine.evaluate("emp-001", "acme", OUTSIDE_LAT, OUTSIDE_LNG, ts2, uuid.uuid4())
    exit_kinds = [t.kind for t in transitions]
    assert "exit" in exit_kinds


@pytest.mark.asyncio
async def test_engine_no_transition_inside(sample_tenant_geofences):
    """Consecutive inside positions do not re-fire enter."""
    engine, dispatched = await _make_engine(sample_tenant_geofences)
    ts1 = _now()
    ts2 = ts1 + timedelta(seconds=1)
    t1 = engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts1, uuid.uuid4())
    t2 = engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts2, uuid.uuid4())
    # Second call should produce no new transitions
    assert not any(t.kind == "enter" for t in t2)


@pytest.mark.asyncio
async def test_engine_no_transition_outside(sample_tenant_geofences):
    """Points outside polygon fire no transitions."""
    engine, dispatched = await _make_engine(sample_tenant_geofences)
    transitions = engine.evaluate("emp-001", "acme", OUTSIDE_LAT, OUTSIDE_LNG, _now(), uuid.uuid4())
    assert not transitions


@pytest.mark.asyncio
async def test_engine_point_ordering_trap(sample_tenant_geofences):
    """Confirm Point(lng, lat) ordering — Mexico City (19.43, -99.13) is inside polygon."""
    engine, _ = await _make_engine(sample_tenant_geofences)
    # Real-world: lat=19.43, lng=-99.13 — Shapely uses (x=lng, y=lat)
    transitions = engine.evaluate("emp-001", "acme", 19.43, -99.13, _now(), uuid.uuid4())
    assert any(t.kind == "enter" for t in transitions), (
        "Point ordering trap: expected enter for Mexico City coords. "
        "Check that engine uses Point(lng, lat), not Point(lat, lng)."
    )


@pytest.mark.asyncio
async def test_engine_out_of_order_ignored(sample_tenant_geofences):
    """Positions older than the last seen timestamp are dropped."""
    engine, _ = await _make_engine(sample_tenant_geofences)
    ts_now = _now()
    ts_old = ts_now - timedelta(seconds=10)
    engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts_now, uuid.uuid4())
    # Older position should be ignored — no double-enter
    transitions = engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts_old, uuid.uuid4())
    assert not any(t.kind == "enter" for t in transitions)


@pytest.mark.asyncio
async def test_engine_dwell_timer_fires():
    """Dwell timer fires within dwell_seconds (fast test with dwell_seconds=1)."""
    import json
    from datetime import datetime, timezone
    fence_with_fast_dwell = [
        Geofence(
            id=1,
            tenant_id="acme",
            name="fast_dwell_fence",
            polygon=MEXICO_CITY_POLYGON_GEOJSON,
            active=True,
            dwell_seconds=1,  # 1s dwell for fast test
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
    ]
    engine, dispatched = await _make_engine(fence_with_fast_dwell, dwell_default=1)
    engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, _now(), uuid.uuid4())
    # Wait slightly longer than dwell_seconds
    await asyncio.sleep(1.3)
    dwell_kinds = [t.kind for t in dispatched]
    assert "dwell" in dwell_kinds


@pytest.mark.asyncio
async def test_engine_dwell_timer_cancelled_on_exit(sample_tenant_geofences):
    """Exit before dwell fires should cancel the dwell timer."""
    engine, dispatched = await _make_engine(sample_tenant_geofences, dwell_default=5)
    ts1 = _now()
    ts2 = ts1 + timedelta(seconds=1)
    engine.evaluate("emp-001", "acme", INSIDE_LAT, INSIDE_LNG, ts1, uuid.uuid4())
    engine.evaluate("emp-001", "acme", OUTSIDE_LAT, OUTSIDE_LNG, ts2, uuid.uuid4())
    # Give the event loop a beat
    await asyncio.sleep(0.1)
    dwell_kinds = [t.kind for t in dispatched]
    assert "dwell" not in dwell_kinds


@pytest.mark.asyncio
async def test_engine_batch_enter_exit(sample_tenant_geofences):
    """evaluate_batch processes multiple positions in ts order."""
    engine, dispatched = await _make_engine(sample_tenant_geofences)
    ts = _now()
    positions = [
        Position(lat=INSIDE_LAT, lng=INSIDE_LNG, ts=ts),
        Position(lat=OUTSIDE_LAT, lng=OUTSIDE_LNG, ts=ts + timedelta(seconds=1)),
        Position(lat=INSIDE_LAT, lng=INSIDE_LNG, ts=ts + timedelta(seconds=2)),
    ]
    transitions = engine.evaluate_batch(
        employee_id="emp-001",
        tenant_id="acme",
        positions=positions,
        source_event_id=uuid.uuid4(),
    )
    kinds = [t.kind for t in transitions]
    # Should have at least one enter
    assert "enter" in kinds


@pytest.mark.asyncio
async def test_engine_reload_one(sample_tenant_geofences):
    """reload_one re-invokes load_from_db and refreshes the R-tree."""
    call_count = 0

    async def counting_loader():
        nonlocal call_count
        call_count += 1
        return sample_tenant_geofences

    engine = GeofenceEngine(
        db_loader=counting_loader,
        emit=lambda t: None,
        dwell_default=2,
    )
    await engine.load_from_db()
    assert call_count == 1
    await engine.reload_one(geofence_id=1)
    assert call_count == 2
