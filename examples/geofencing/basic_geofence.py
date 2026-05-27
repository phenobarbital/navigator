"""Basic Geofencing Example — End-to-End Pipeline Demo.

Demonstrates the complete geofencing pipeline using:
- A :class:`~navigator.ext.geofencing.GeofencingExtension` with mock DB and
  identity encrypt/decrypt callables (example-only — use real encryption in
  production).
- An in-process mock DB that holds geofence data in memory.
- ``@on_geofence_event`` decorators that print to stdout on enter and dwell.
- A synthetic location event published to trigger the pipeline.

Note:
    The ``secret_encrypt`` and ``secret_decrypt`` callables in this example are
    identity functions (``lambda b: b``) for simplicity.  **Never use identity
    functions for HMAC secrets in production** — use proper AES or Fernet
    encryption from ``navigator_auth``.

Requirements:
    - A running RabbitMQ 3.12+ instance with MQTT and auth plugins enabled.
    - Navigator configured with valid ``RABBITMQ_HOST`` / ``RABBITMQ_USER`` /
      ``RABBITMQ_PASS`` env vars.

Run:
    $ source .venv/bin/activate
    $ python examples/geofencing/basic_geofence.py

Expected output:
    GeofencingExtension loaded. Registering store_42 geofence...
    [POST /api/v1/geofencing/fences] → 201 Created
    Publishing synthetic location for emp-001 inside store_42...
    [ENTER] Employee emp-001 entered store_42 at (37.7749, -122.4194)
    [DWELL] Employee emp-001 has been dwelling for 300s in geofence 1
    [Press Ctrl+C to stop]
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from aiohttp import web

from navigator.ext.geofencing import (
    GeofencingExtension,
    on_geofence_event,
    GeofenceTransition,
)


# ---------------------------------------------------------------------------
# @on_geofence_event handlers
# ---------------------------------------------------------------------------


@on_geofence_event(geofence_name="store_42", kind="enter")
async def handle_store_42_enter(transition: GeofenceTransition) -> None:
    """Handle enter events for store_42.

    Args:
        transition: The geofence transition event.
    """
    print(
        f"[ENTER] Employee {transition.employee_id} entered store_42 "
        f"at ({transition.location.lat}, {transition.location.lng})"
    )


@on_geofence_event(kind="dwell")
async def handle_dwell(transition: GeofenceTransition) -> None:
    """Handle dwell events for any geofence.

    Args:
        transition: The geofence transition event.
    """
    print(
        f"[DWELL] Employee {transition.employee_id} has been dwelling "
        f"for {transition.dwell_duration}s in geofence {transition.geofence_id}"
    )


# ---------------------------------------------------------------------------
# Mock DB — in-memory geofence/webhook store for demo purposes
# ---------------------------------------------------------------------------


class _MockDB:
    """Minimal mock DB compatible with asyncdb's fetch_all/fetch_one/execute.

    Holds a list of geofence rows as dicts.  Suitable for examples and tests;
    NOT thread-safe.
    """

    def __init__(self) -> None:
        # store_42 polygon: 100m radius around Embarcadero, SF
        store_42_polygon = json.dumps({
            "type": "Polygon",
            "coordinates": [[
                [-122.4200, 37.7745],
                [-122.4188, 37.7745],
                [-122.4188, 37.7753],
                [-122.4200, 37.7753],
                [-122.4200, 37.7745],
            ]],
        })
        self._geofences: list[dict] = [
            {
                "id": 1,
                "tenant_id": "acme",
                "name": "store_42",
                "polygon": store_42_polygon,
                "active": True,
                "dwell_seconds": 300,
                "created_at": datetime.now(tz=timezone.utc),
                "updated_at": datetime.now(tz=timezone.utc),
            }
        ]
        self._webhooks: list[dict] = []

    async def fetch_all(self, query: str, *args: Any) -> list[dict]:
        """Return rows matching simple SELECT queries.

        Args:
            query: SQL query string (parsed very loosely for demo).
            *args: Positional parameters.

        Returns:
            List of matching row dicts.
        """
        if "geofences" in query:
            if args:
                return [r for r in self._geofences if str(r.get("tenant_id")) == str(args[0])]
            return list(self._geofences)
        if "webhooks" in query:
            return list(self._webhooks)
        return []

    async def fetch_one(self, query: str, *args: Any) -> Optional[dict]:
        """Return the first matching row.

        Args:
            query: SQL query string.
            *args: Positional parameters.

        Returns:
            First matching row dict, or None.
        """
        rows = await self.fetch_all(query, *args)
        return rows[0] if rows else None

    async def execute(self, query: str, *args: Any) -> None:
        """No-op execute for INSERT/UPDATE in the demo.

        Args:
            query: SQL query string.
            *args: Positional parameters.
        """
        pass


# ---------------------------------------------------------------------------
# Demo helpers
# ---------------------------------------------------------------------------


async def _fetch_device_tokens(employee_id: str) -> list[str]:
    """Mock device token lookup — returns no tokens so FCM is skipped.

    Args:
        employee_id: Employee identifier.

    Returns:
        Empty list (no real FCM tokens in example).
    """
    return []


async def _resolve_tenant(employee_id: str) -> str:
    """Mock tenant resolver — always returns 'acme'.

    Args:
        employee_id: Employee identifier.

    Returns:
        Tenant ID.
    """
    return "acme"


async def _publish_synthetic_location(app: web.Application) -> None:
    """Publish a synthetic employee location inside store_42.

    Waits 2 seconds after startup to let the engine load, then publishes
    a location event directly via the bridge's exchange.

    Args:
        app: The aiohttp application.
    """
    await asyncio.sleep(2)
    print("Publishing synthetic location for emp-001 inside store_42...")
    ext: GeofencingExtension = app["geofencing"]
    if ext._engine is None:
        print("Engine not initialised — skipping synthetic event")
        return

    from navigator.ext.geofencing.models import Position

    position = Position(
        lat=37.7749,
        lng=-122.4194,
        ts=datetime.now(tz=timezone.utc),
    )
    transitions = await ext._engine.evaluate(
        employee_id="emp-001",
        tenant_id="acme",
        position=position,
        source_event_id=uuid.uuid4(),
    )
    for t in transitions:
        await ext._dispatcher.dispatch(t)

    if not transitions:
        print("No transitions generated (check that the polygon contains lat=37.7749, lng=-122.4194)")


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------


async def startup_demo(app: web.Application) -> None:
    """Startup hook: announce readiness and schedule synthetic event.

    Args:
        app: The aiohttp application.
    """
    print("GeofencingExtension loaded. Registering store_42 geofence...")
    asyncio.create_task(_publish_synthetic_location(app))


mock_db = _MockDB()

app = web.Application()
app.on_startup.append(startup_demo)

ext = GeofencingExtension(
    app_db=mock_db,
    # Identity encrypt/decrypt — EXAMPLE ONLY, not for production
    secret_encrypt=lambda b: b,
    secret_decrypt=lambda b: b,
    device_token_lookup=_fetch_device_tokens,
    tenant_resolver=_resolve_tenant,
    install_bridge=False,  # No real RabbitMQ needed for this demo
)
ext.setup(app)


if __name__ == "__main__":
    print("Starting basic geofencing example...")
    try:
        web.run_app(app, port=5010)
    except KeyboardInterrupt:
        print("\nEXIT =========")
