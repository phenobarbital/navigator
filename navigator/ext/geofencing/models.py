"""Geofencing domain dataclasses.

Defines the four core data models shared across the geofencing subsystem:
:class:`Position`, :class:`Geofence`, :class:`GeofenceTransition`, and
:class:`Webhook`.

All models use ``slots=True`` for memory efficiency and attribute access
speed, consistent with the project's performance requirements.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` §2 "Data Models" and Module 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID


@dataclass(slots=True)
class Position:
    """Single GPS fix within a location batch.

    Attributes:
        lat: Latitude in decimal degrees (WGS-84).
        lng: Longitude in decimal degrees (WGS-84).
        ts: UTC timestamp of this GPS fix.
    """

    lat: float
    lng: float
    ts: datetime


@dataclass(slots=True)
class Geofence:
    """Tenant-scoped geofence polygon stored in the ``geofences`` table.

    The polygon is stored as GeoJSON or WKT text in the ``polygon`` column.
    No PostGIS dependency — evaluation is in-memory via Shapely.

    Attributes:
        id: Primary key.
        tenant_id: Owning tenant identifier (NOT NULL).
        name: Human-readable geofence name.
        polygon: Polygon definition as GeoJSON or WKT string.
        active: Whether this geofence is evaluated.
        dwell_seconds: Per-geofence dwell override in seconds.
            ``None`` means use the global ``GEOFENCE_DWELL_DURATION`` config.
        created_at: Record creation timestamp.
        updated_at: Last-modified timestamp.
    """

    id: int
    tenant_id: str
    name: str
    polygon: str  # GeoJSON or WKT — no PostGIS required
    active: bool
    dwell_seconds: Optional[int]  # None → use GEOFENCE_DWELL_DURATION global
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class GeofenceTransition:
    """Emitted by :class:`~navigator.ext.geofencing.engine.GeofenceEngine`
    on every enter / exit / dwell event.

    Attributes:
        employee_id: Employee whose position triggered this transition.
        geofence_id: Foreign key to :class:`Geofence`.
        tenant_id: Tenant that owns the geofence.
        kind: Transition type — ``"enter"``, ``"exit"``, or ``"dwell"``.
        location: GPS fix that caused the transition.
        ts: Timestamp of the triggering position fix.
        source_event_id: UUID of the upstream MQTT event batch.
        dwell_duration: Duration inside the geofence in seconds; only
            populated when ``kind == "dwell"``.
    """

    employee_id: str
    geofence_id: int
    tenant_id: str
    kind: Literal["enter", "exit", "dwell"]
    location: Position
    ts: datetime
    source_event_id: UUID
    dwell_duration: Optional[int]  # seconds; only populated for kind="dwell"


@dataclass(slots=True)
class Webhook:
    """Per-tenant outbound webhook target with HMAC-SHA256 secret.

    The ``secret_encrypted`` field stores the HMAC signing key encrypted at
    rest via ``navigator_auth`` secret-storage primitives.  It is decrypted
    just-in-time when dispatching a webhook POST.

    Attributes:
        id: Primary key.
        tenant_id: Owning tenant identifier (NOT NULL).
        url: Target HTTPS endpoint.
        secret_encrypted: Encrypted HMAC signing key bytes.
        geofence_filter: If set, the webhook only fires for this
            :class:`Geofence` id.  ``None`` means "fire for all transitions".
        active: Whether this webhook is dispatched.
        created_at: Record creation timestamp.
        updated_at: Last-modified timestamp.
    """

    id: int
    tenant_id: str
    url: str
    secret_encrypted: bytes  # decrypted at dispatch; never returned by API
    geofence_filter: Optional[int]  # if set, fires only for this geofence
    active: bool
    created_at: datetime
    updated_at: datetime
