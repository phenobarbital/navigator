# Feature Specification: MQTT + RabbitMQ Broker with Geofencing

**Feature ID**: FEAT-005
**Date**: 2026-05-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Source brainstorm**: `sdd/proposals/mqtt-rabbitmq-broker.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

Navigator currently exposes RabbitMQ (`aiormq`), Redis pub/sub and AWS SQS brokers in
`navigator/brokers/`, but has **no MQTT support and no geofencing layer**. A workforce-style
mobile app needs to publish high-frequency telemetry (`employees/{employeeId}/location`,
`…/status`, `…/events/check-in`, `…/events/incidents`) over **MQTT/TLS** from devices,
ingest those messages through Navigator, fan them out to internal services over RabbitMQ
(`employee.location.updated` → `location-service.queue`, `analytics.queue`, `audit.queue`;
`employee.incident.created` → `incident-service.queue`, `notification-service.queue`,
`audit.queue`), and **react to geofence enter/exit/dwell events** in near real-time —
pushing notifications back to the device, calling registered Python handlers, hitting
HMAC-signed webhooks, and forwarding to FCM push (iOS via FCM's APNs bridge in v1; native
APNs deferred to v2).

The canonical telemetry envelope is **batched**:

```json
{
  "eventId": "uuid-v4",
  "employeeId": "123",
  "type": "location.batch",
  "schemaVersion": 1,
  "positions": [
    { "lat": 19.43, "lng": -99.13, "ts": "2026-05-27T10:15:01.220Z" },
    { "lat": 19.44, "lng": -99.14, "ts": "2026-05-27T10:15:06.180Z" }
  ]
}
```

Single-fix messages are batches of length 1 — no separate `location.single` type. Non-location
events (`status`, `events/check-in`, `events/incidents`) use the flat envelope
`{eventId, employeeId, type, schemaVersion, payload, timestamp}`. `eventId` is mandated as a
v4 UUID and is used downstream for idempotent processing (Redis TTL set).

### Goals

- Enable mobile devices to publish MQTT/TLS telemetry to RabbitMQ's MQTT plugin and
  subscribe to per-employee downlink topics for notifications.
- Add an **ingestion bridge** (`EmployeeEventsBridge`) that consumes from `amq.topic` /
  `employees.#`, performs `eventId`-based dedup, validates `schemaVersion`, enforces
  envelope-vs-JWT `employeeId` consistency, fans batched `positions[]` into per-position
  AMQP messages, and republishes to a domain `employee.events` topic exchange.
- Add a **downlink publisher** (`MQTTDownlinkPublisher`) for AMQP-side fan-out that the
  RabbitMQ MQTT plugin delivers to subscribed mobile devices.
- Add a **per-tenant Shapely R-tree geofence engine** with hot-reload via pub/sub,
  per-`(employee, geofence)` dwell timers, intra-batch transition collapsing, and a
  stable `evaluate_batch(...)` API surface that a v2 Cython hot-path can slot into.
- Add tenant-scoped admin **REST CRUD** endpoints for `geofences` and `webhooks` plus a
  `geofence.changed` fanout for multi-instance reload.
- Add a **`@on_geofence_event(...)` decorator registry** for in-process Python handlers
  filterable by `geofence_name` / `kind` / `employee_id` / `tenant_id`.
- Add a **multi-channel `NotificationDispatcher`**: MQTT downlink, **FCM-only** push,
  internal RabbitMQ fanout, HMAC-SHA256-signed webhooks, in-process Python callbacks.
- Add four aiohttp handlers `/api/v1/mqtt/auth/{user,vhost,resource,topic}` for
  `rabbitmq_auth_backend_http`, delegating JWT decoding/validation to `navigator_auth`'s
  existing helpers (no parallel JWT logic).
- Ship an ops runbook for enabling `rabbitmq_mqtt`, `rabbitmq_web_mqtt`,
  `rabbitmq_auth_backend_http`, TLS listener config, and per-connection rate-limit policies.

### Non-Goals (explicitly out of scope)

- **No first-class MQTT transport in Navigator.** Per Option A, Navigator only speaks
  AMQP via `aiormq`; mobile clients speak MQTT to RabbitMQ; the plugin bridges both
  directions. `aiomqtt` / `paho-mqtt` are not added in v1.
- **No native APNs provider.** iOS coverage in v1 goes through FCM's APNs bridge.
  `aioapns` integration is deferred to v2 behind the same `PushProvider` interface.
- **No Redis-backed shared transition state.** Each Navigator instance keeps its own
  per-employee `inside` set; multi-instance duplicate transitions are absorbed by
  downstream audit dedup. Redis-backed shared state is a v2 concern.
- **No persisted dwell timers across restarts.** v1 cancels timers on `exit` and rebuilds
  on process restart.
- **No v2 Cython hot-path** (`navigator/ext/geofencing/_engine_fast.pyx`). The Python
  `evaluate_batch(...)` surface is shipped now so the migration is later additive.
- **No new JWT issuer.** Mobile auth reuses the existing `navigator_auth` token; MQTT
  scopes (`mqtt.subscribe:*`, `mqtt.publish:*`) are added to its scope registry.
- **No Navigator-side rate limiter.** Per-connection MQTT publish limits live in
  `rabbitmq.conf` policies (documented in the ops runbook).
- **No PostGIS dependency.** Polygons are stored as GeoJSON/WKT in a plain SQL column;
  evaluation is in-memory Shapely.

---

## 2. Architectural Design

### Overview

A mobile device opens an MQTT/TLS connection to RabbitMQ's MQTT plugin. The plugin
HTTP-calls Navigator's `/api/v1/mqtt/auth/{user,vhost,resource,topic}` endpoints for
authentication and per-topic ACL checks, which delegate to `navigator_auth`. On publish,
the plugin translates `employees/123/location` to an AMQP message on `amq.topic` with
routing key `employees.123.location`. `EmployeeEventsBridge` (an `RMQConsumer`) consumes
that, dedups by `eventId` via Redis, validates `schemaVersion`, cross-checks
`employeeId` against the MQTT username (JWT `sub`), and **fans the `positions[]` array
into one AMQP message per position** on a new domain exchange `employee.events` with
keys like `employee.location.updated`. Existing internal queues bind there as usual.

A second consumer — `GeofenceConsumer` — also binds to `employee.events` with
`employee.location.updated`, resolves the employee's tenant via cached
`navigator_auth` lookup, asks `GeofenceEngine.evaluate(employee_id, lat, lon)`, and
hands each `GeofenceTransition` (enter / exit / dwell) to `NotificationDispatcher`,
which fans out concurrently to MQTT downlink (via `MQTTDownlinkPublisher` →
`amq.topic` / `employees.123.notifications` → MQTT plugin → device), FCM push,
internal RabbitMQ fanout `geofence.notifications`, HMAC-signed webhooks, and matching
`@on_geofence_event` Python handlers.

Geofence CRUD goes through tenant-scoped REST endpoints; mutations publish
`geofence.changed` on a fanout exchange so every instance's per-tenant R-tree
reloads atomically.

### Component Diagram

```
                       [Mobile App, MQTT/TLS]
                               │
                               │ publish/subscribe
                               ▼
                  ┌────────────────────────────┐
                  │  RabbitMQ MQTT Plugin      │
                  │  (rabbitmq_mqtt,           │
                  │   rabbitmq_auth_backend_   │
                  │   http)                    │
                  └────────────────────────────┘
                    │            │           ▲
                    │ AMQP       │ HTTP      │ AMQP downlink
                    │ amq.topic  │ /mqtt/auth/*│ amq.topic
                    ▼            ▼           │
        ┌──────────────────┐  ┌──────────────────────────────┐
        │EmployeeEventsBridge│  │/api/v1/mqtt/auth/{user,vhost,│
        │ (RMQConsumer)    │  │ resource,topic} handlers     │
        │ - dedup (Redis)  │  │ (delegates → navigator_auth) │
        │ - schemaVersion  │  └──────────────────────────────┘
        │ - employeeId check│
        │ - batch fan-out  │
        └──────────────────┘                  ▲ publish notifications
                  │ republish per-position    │
                  ▼                           │
        ┌────────────────────────────────┐    │
        │ employee.events (topic exchange)│    │
        │  routing keys:                 │    │
        │   employee.location.updated    │    │
        │   employee.incident.created    │    │
        │   employee.status.updated      │    │
        │   employee.checkin.recorded    │    │
        └────────────────────────────────┘    │
            │                       │         │
            │ bind                  │ bind    │
            ▼                       ▼         │
   ┌──────────────────┐    ┌──────────────────────┐
   │ external service │    │ GeofenceConsumer     │
   │ queues:          │    │ (RMQConsumer)        │
   │  location-svc.q  │    │ - tenant lookup      │
   │  analytics.q     │    │ - engine.evaluate()  │
   │  audit.q         │    └──────────────────────┘
   │  ...             │              │
   └──────────────────┘              ▼
                              ┌──────────────────────────┐
                              │ GeofenceEngine           │
                              │ - per-tenant STRtree     │
                              │ - _inside per employee   │
                              │ - _entered_at + timers   │
                              │ - evaluate / evaluate_batch│
                              └──────────────────────────┘
                                          │ GeofenceTransition
                                          ▼
                              ┌──────────────────────────┐
                              │ NotificationDispatcher   │
                              │ fan-out:                 │
                              │  - MQTT downlink         │──┐
                              │  - FCM push (HTTP v1)    │  │
                              │  - geofence.notifications│  │
                              │    (RabbitMQ fanout)     │  │
                              │  - HMAC-signed webhooks  │  │
                              │  - @on_geofence_event    │  │
                              └──────────────────────────┘  │
                                          ▲                 │
                                          │                 │
                              ┌──────────────────────────┐  │
                              │ CRUD: /api/v1/geofencing/│  │
                              │  fences, webhooks        │  │
                              │  publishes geofence.changed│ │
                              │  (fanout) → reload       │  │
                              └──────────────────────────┘  │
                                                            ▼
                                            [MQTTDownlinkPublisher → AMQP →
                                             RabbitMQ MQTT plugin → Device]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.brokers.rabbitmq.RMQConsumer` | extends | `EmployeeEventsBridge`, `GeofenceConsumer` subclass `RMQConsumer` |
| `navigator.brokers.rabbitmq.RMQProducer` | extends | `MQTTDownlinkPublisher` subclasses `RMQProducer` |
| `navigator.brokers.connection.BaseConnection.setup(app)` | uses | `on_startup` / `on_shutdown` signal registration |
| `navigator.extensions.BaseExtension` | extends | `GeofencingExtension` follows this pattern |
| `navigator.ext.redis.RedisConnection` | uses (CACHE_URL) | `eventId` Redis dedup uses the same Redis instance |
| `navigator.conf.rabbitmq_dsn` | uses | Existing DSN for AMQP connections |
| `navigator_auth` (existing helpers) | uses + light modify | JWT decode/validate reused; new MQTT scope namespace registered |
| `navigator_auth` secret-storage primitives | uses | Webhook secret encryption at rest |
| `navigator.handlers` package | adds module | `mqtt_auth.py` exposes 4 aiohttp handlers |
| `aiohttp.web.Application` | uses | Route registration via `app.router.add_get/post/patch/delete` |
| `pyproject.toml` | modify | `uv add shapely` adds `shapely>=2.0` |

### Data Models

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

@dataclass(slots=True)
class Position:
    """Single GPS fix within a location batch."""
    lat: float
    lng: float
    ts: datetime

@dataclass(slots=True)
class Geofence:
    """Tenant-scoped geofence polygon."""
    id: int
    tenant_id: str
    name: str
    polygon: str           # GeoJSON or WKT
    active: bool
    dwell_seconds: Optional[int]  # per-geofence override; None → use GEOFENCE_DWELL_DURATION
    created_at: datetime
    updated_at: datetime

@dataclass(slots=True)
class GeofenceTransition:
    """Emitted by GeofenceEngine on every enter/exit/dwell event."""
    employee_id: str
    geofence_id: int
    tenant_id: str
    kind: Literal["enter", "exit", "dwell"]
    location: Position
    ts: datetime
    source_event_id: UUID
    dwell_duration: Optional[int]   # populated only when kind == "dwell"

@dataclass(slots=True)
class Webhook:
    """Per-tenant outbound webhook target with HMAC secret."""
    id: int
    tenant_id: str
    url: str
    secret_encrypted: bytes      # decrypted on dispatch
    geofence_filter: Optional[int]  # if set, only fires for this geofence
    active: bool
```

### New Public Interfaces

```python
# navigator/brokers/rabbitmq/bridge.py
class EmployeeEventsBridge(RMQConsumer):
    """Consumes MQTT-originated messages from amq.topic / employees.# and
    republishes per-position AMQP messages to employee.events with normalized keys."""
    def __init__(self, *, dedup_ttl: int = 600,
                 accepted_schema_versions: set[int] = {1},
                 max_batch_size: int = 200,
                 enforce_employee_id: bool = True,
                 employee_events_exchange: str = "employee.events",
                 **kwargs): ...
    async def start(self, app): ...  # subscribe to amq.topic / employees.#

# navigator/brokers/rabbitmq/downlink.py
class MQTTDownlinkPublisher(RMQProducer):
    """Thin RMQProducer wrapper for AMQP→MQTT-plugin downlink."""
    async def publish_to_employee(self, employee_id: str, topic: str,
                                  payload: dict) -> None: ...

# navigator/ext/geofencing/engine.py
class GeofenceEngine:
    """Per-tenant in-memory Shapely STRtree evaluator with dwell timers."""
    async def load_from_db(self) -> None: ...
    async def reload_one(self, geofence_id: int) -> None: ...
    def evaluate(self, employee_id: str, tenant_id: str,
                 lat: float, lng: float, ts: datetime,
                 source_event_id: UUID) -> list[GeofenceTransition]: ...
    def evaluate_batch(self, employee_id: str, tenant_id: str,
                       positions: list[Position],
                       source_event_id: UUID) -> list[GeofenceTransition]: ...

# navigator/ext/geofencing/decorators.py
def on_geofence_event(*, geofence_name: str | None = None,
                      kind: Literal["enter","exit","dwell"] | None = None,
                      employee_id: str | None = None,
                      tenant_id: str | None = None) -> Callable: ...
"""Register a coroutine in the in-process dispatcher registry.
Filters are conjunctive; None means 'any'."""

# navigator/ext/geofencing/dispatcher.py
class NotificationDispatcher:
    """Fan-out engine for GeofenceTransition events."""
    async def dispatch(self, transition: GeofenceTransition) -> None: ...

# navigator/ext/geofencing/__init__.py
class GeofencingExtension(BaseExtension):
    name: str = "geofencing"
    def setup(self, app): ...  # registers CRUD routes, starts engine + dispatcher

# navigator/handlers/mqtt_auth.py
async def mqtt_auth_user(request: web.Request) -> web.Response: ...
async def mqtt_auth_vhost(request: web.Request) -> web.Response: ...
async def mqtt_auth_resource(request: web.Request) -> web.Response: ...
async def mqtt_auth_topic(request: web.Request) -> web.Response: ...
```

---

## 3. Module Breakdown

### Module 1: Configuration & Dependency
- **Path**: `navigator/conf.py` (modify, append-only); `pyproject.toml` (via `uv add shapely`).
- **Responsibility**: Add config keys (see "External Dependencies / Config" below).
  Run `uv add shapely` to introduce `shapely>=2.0`. PyJWT is already transitive via
  `navigator_auth`. No `MQTT_JWT_SECRET`, no `APNS_*` keys.
- **Depends on**: nothing.

### Module 2: MQTT Auth Handlers
- **Path**: `navigator/handlers/mqtt_auth.py`
- **Responsibility**: Four aiohttp handlers
  (`/api/v1/mqtt/auth/{user,vhost,resource,topic}`) that `rabbitmq_auth_backend_http`
  HTTP-calls. Each delegates JWT decode/validation to `navigator_auth`'s existing helpers
  and returns plain-text `allow` / `deny` per the RabbitMQ HTTP-backend spec. Topic ACL
  enforces that an employee may only `mqtt.subscribe:employees.{their_id}.#` and
  `mqtt.publish:employees.{their_id}.#`; admin scopes get broader access. In-memory TTL
  cache controlled by `MQTT_AUTH_CACHE_TTL`.
- **Depends on**: Module 1, `navigator_auth` (existing JWT helpers + scope registry —
  light modification to add `mqtt.subscribe:*` / `mqtt.publish:*` scopes).

### Module 3: Ingestion Bridge
- **Path**: `navigator/brokers/rabbitmq/bridge.py`
- **Responsibility**: `EmployeeEventsBridge(RMQConsumer)` subscribes to `amq.topic` with
  routing key `employees.#`. For each message:
  1. Parses JSON envelope (`json_decoder` from existing serializer path).
  2. Checks `eventId` against Redis TTL set (`MQTT_EVENT_DEDUP_TTL`); per-position
     dedup keys are `{eventId}:{positionIndex}`. Fail-open on Redis down (log WARNING,
     republish anyway).
  3. Validates `schemaVersion ∈ MQTT_ACCEPTED_SCHEMA_VERSIONS`; rejects to
     `employee.events.dlq.schema` otherwise.
  4. **Enforces** `envelope.employeeId == message.properties.user_id` (the MQTT
     username propagated from JWT `sub`); mismatch → DLQ + WARNING with
     `mqtt_username`, `envelope_employee_id`, `eventId`, source IP.
  5. If `type == "location.batch"` and `len(positions) > MQTT_MAX_BATCH_SIZE` → DLQ.
  6. If `type == "location.batch"`: iterates `positions[]` and publishes one AMQP
     message per position to `employee.events` with key `employee.location.updated`,
     body `{employeeId, lat, lng, ts}`, headers `{eventId, positionIndex, batchSize,
     tenantId}`. Empty `positions[]` → DLQ.
  7. For non-batched envelopes: maps `events/check-in` → `employee.checkin.recorded`,
     `events/incidents` → `employee.incident.created`, `status` →
     `employee.status.updated`, publishes one AMQP message per MQTT message.
- **Depends on**: Module 1, `navigator.brokers.rabbitmq.RMQConsumer`,
  `navigator.ext.redis` (for dedup; uses `CACHE_URL` by default,
  `MQTT_EVENT_DEDUP_REDIS_URL` override).

### Module 4: MQTT Downlink Publisher
- **Path**: `navigator/brokers/rabbitmq/downlink.py`
- **Responsibility**: `MQTTDownlinkPublisher(RMQProducer)` exposes
  `publish_to_employee(employee_id, topic, payload)` that calls `queue_event(...)` on
  the parent's worker queue with `queue_name="amq.topic"` and
  `routing_key=f"employees.{employee_id}.{topic}"`. Body is JSON-encoded via the
  existing `publish_message` path.
- **Depends on**: Module 1, `navigator.brokers.rabbitmq.RMQProducer`.

### Module 5: Geofence Models & DB Migration
- **Path**: `navigator/ext/geofencing/models.py`; migration script
  (location per project conventions — TBD with task author; recommended:
  `db/migrations/<timestamp>_geofencing.sql`).
- **Responsibility**: `Position`, `Geofence`, `GeofenceTransition`, `Webhook` dataclasses
  (see Data Models). SQL migration creates:
  - `geofences (id, tenant_id NOT NULL, name, polygon, active, dwell_seconds NULL,
    created_at, updated_at)` with index `(tenant_id, active)`.
  - `webhooks (id, tenant_id NOT NULL, url, secret_encrypted, geofence_filter NULL,
    active, created_at, updated_at)` with index `(tenant_id, active)`.
- **Depends on**: Module 1.

### Module 6: Geofence Engine
- **Path**: `navigator/ext/geofencing/engine.py`
- **Responsibility**: `GeofenceEngine` with:
  - `_trees: dict[tenant_id, shapely.strtree.STRtree]` — one R-tree per tenant.
  - `_polys_by_tenant: dict[tenant_id, list[(geofence_id, shapely.geometry.Polygon, dwell_seconds)]]`.
  - `_inside: dict[str, set[int]]` — per-employee set of geofence_ids currently entered.
  - `_entered_at: dict[(str, int), datetime]`.
  - `_dwell_timers: dict[(str, int), asyncio.TimerHandle]`.
  - `load_from_db()` builds fresh trees and atomically swaps `_trees` reference.
  - `reload_one(id)` mutates only the affected tenant's tree.
  - `evaluate(employee_id, tenant_id, lat, lng, ts, source_event_id)`:
    selects tenant tree, queries candidates via STRtree, point-in-polygon via
    `shapely.prepared.prep(...).contains(...)`, compares with `_inside[employee_id]`,
    emits `enter` / `exit` transitions on set diff, schedules dwell timers on `enter`
    (using `dwell_seconds` override or `GEOFENCE_DWELL_DURATION` default), cancels
    them on `exit`.
  - `evaluate_batch(employee_id, tenant_id, positions, source_event_id)`:
    Python implementation that loops `positions` (in `ts` order), threads the
    `inside` set forward; if `GEOFENCE_COLLAPSE_INTRA_BATCH=True`, collapses
    enter→exit→enter sequences within the batch to a single final transition.
    API surface is the v2 Cython migration target — implementation stays pure Python.
  - Out-of-order: skip if `ts < last_seen_ts[employee_id]` (configurable, default skip).
- **Depends on**: Module 5, `shapely>=2.0`, `navigator.ext.geofencing` package init.

### Module 7: Decorator Registry & Dispatcher
- **Path**: `navigator/ext/geofencing/decorators.py`; `navigator/ext/geofencing/dispatcher.py`.
- **Responsibility**:
  - `decorators.py` — `@on_geofence_event(geofence_name=None, kind=None,
    employee_id=None, tenant_id=None)` stores `(filters, coroutine)` in a module-level
    `_REGISTRY: list[tuple[Filter, Callable]]`. `get_matching_handlers(transition)`
    returns matches.
  - `dispatcher.py` — `NotificationDispatcher.dispatch(transition)` runs five channels
    concurrently via `asyncio.gather(..., return_exceptions=True)`:
    1. MQTT downlink via injected `MQTTDownlinkPublisher`
       (topic `notifications`, payload includes `kind`, `geofence_id`, `ts`, etc.).
    2. FCM push via `push_providers.fcm.FCMProvider`
       (HTTP v1, service-account JWT; iOS reached via FCM's APNs bridge).
    3. RabbitMQ fanout publish on `geofence.notifications` exchange.
    4. HMAC-SHA256 webhook POST to each matching `Webhook` row
       (tenant + optional geofence filter); headers
       `X-Navigator-Signature: sha256=<hex>` over canonical JSON body,
       `X-Navigator-Timestamp: <unix>`; retries on failure go to a small in-memory
       backoff queue (exponential, 3 attempts) before logging+dropping.
    5. `@on_geofence_event` Python handlers — each wrapped in
       `asyncio.wait_for(..., timeout=GEOFENCE_HANDLER_TIMEOUT)`; exceptions logged
       per-handler; one failing handler does not block others.
- **Depends on**: Modules 4, 5, 6; `aiohttp` (for FCM + webhook HTTP).

### Module 8: Push Providers & Webhooks Helpers
- **Path**: `navigator/ext/geofencing/push_providers/__init__.py`,
  `push_providers/fcm.py`, `webhooks.py`.
- **Responsibility**:
  - `push_providers/__init__.py` — defines `PushProvider` ABC (async `send(device_token,
    payload)`); v2 adds `apns.py` behind the same interface.
  - `push_providers/fcm.py` — `FCMProvider(PushProvider)`: FCM HTTP v1 client (no SDK),
    builds service-account JWT, POSTs to `https://fcm.googleapis.com/v1/projects/.../messages:send`.
  - `webhooks.py` — `sign_payload(body: bytes, secret: bytes) -> str` (HMAC-SHA256 hex),
    `dispatch_webhook(webhook: Webhook, body: dict) -> None` (resolves URL, computes
    signature, POSTs with `X-Navigator-Signature` + `X-Navigator-Timestamp`).
- **Depends on**: Module 5; `aiohttp`; `navigator_auth` secret-storage primitives for
  decrypting `secret_encrypted`.

### Module 9: CRUD Endpoints & Hot Reload
- **Path**: `navigator/ext/geofencing/crud.py`.
- **Responsibility**: REST handlers for:
  - `GET/POST /api/v1/geofencing/fences`,
    `GET/PATCH/DELETE /api/v1/geofencing/fences/{id}` — tenant-scoped (user can only
    operate within their own tenant; cross-tenant requires admin scope). Validates
    polygon with `shapely.validation.explain_validity` on create/update; rejects
    self-intersecting with HTTP 422.
  - `GET/POST /api/v1/geofencing/webhooks`,
    `GET/PATCH/DELETE /api/v1/geofencing/webhooks/{id}` — secret is encrypted on
    write via `navigator_auth` primitives.
  - On any geofence mutation: publishes `geofence.changed` (fanout) with
    `{geofence_id, tenant_id, action: created|updated|deleted}`. Engine subscribes and
    calls `reload_one(id)`.
- **Depends on**: Modules 5, 6; `navigator.brokers.rabbitmq.RMQProducer` for hot-reload
  publish; `navigator_auth` for tenant resolution + admin scope check.

### Module 10: Extension Package & Geofence Consumer
- **Path**: `navigator/ext/geofencing/__init__.py`.
- **Responsibility**:
  - `GeofencingExtension(BaseExtension)` (`name = "geofencing"`) that on
    `setup(app)`:
    1. Instantiates `GeofenceEngine` and a `GeofenceConsumer(RMQConsumer)` bound to
       `employee.events` / `employee.location.updated`.
    2. Instantiates `MQTTDownlinkPublisher` and `NotificationDispatcher`.
    3. Registers CRUD routes from Module 9.
    4. Hooks `on_startup` → `await engine.load_from_db(); start consumer +
       downlink publisher workers; subscribe to geofence.changed fanout`.
    5. Hooks `on_shutdown` → cancel dwell timers, drain dispatcher queue, close
       broker connections.
  - Re-exports the public surface (`GeofenceEngine`, `on_geofence_event`,
    `GeofenceTransition`, `NotificationDispatcher`, `Geofence`, `Position`,
    `Webhook`).
- **Depends on**: All previous geofencing modules; Module 4 (downlink); Module 3
  (bridge runs in a sibling extension or is wired in the same setup).

### Module 11: Ops Docs & Examples
- **Path**: `docs/ops/rabbitmq-mqtt.md`;
  `examples/brokers/nav_mqtt_bridge.py`;
  `examples/geofencing/basic_geofence.py`.
- **Responsibility**:
  - Runbook for enabling `rabbitmq_mqtt`, `rabbitmq_web_mqtt`,
    `rabbitmq_auth_backend_http` in `rabbitmq.conf`, TLS listener config on port 8883,
    sample per-connection rate-limit policies (`max-publishing-rate`,
    `max-connections-per-user`).
  - End-to-end bridge example mirroring `examples/brokers/nav_rabbitmq_consumer.py`.
  - Geofencing example: define a geofence via CRUD, register two
    `@on_geofence_event(geofence_name="store_42", kind="enter")` /
    `@on_geofence_event(kind="dwell")` handlers, configure FCM credentials and an
    HMAC webhook, simulate a location publish, observe the fan-out.
- **Depends on**: All other modules (used as reference).

### Module 12: Tests
- **Path**: `tests/brokers/test_mqtt_bridge.py`,
  `tests/ext/geofencing/test_engine.py`,
  `tests/ext/geofencing/test_dispatcher.py`,
  `tests/ext/geofencing/test_crud.py`,
  `tests/handlers/test_mqtt_auth.py`.
- **Responsibility**: Unit tests with mocked RabbitMQ/Redis where appropriate;
  integration tests using a RabbitMQ container with the MQTT plugin enabled
  (CI-conditional). Coverage per the Test Specification table below.
- **Depends on**: All modules, `pytest`, `pytest-asyncio`, `aiohttp.test_utils`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_bridge_envelope_dedup_hit` | 3 | Same `eventId` twice → second republish skipped (Redis hit). |
| `test_bridge_envelope_dedup_miss` | 3 | Fresh `eventId` → republish happens. |
| `test_bridge_dedup_redis_down_fails_open` | 3 | Redis unavailable → republish anyway, WARNING logged. |
| `test_bridge_schema_version_accepted` | 3 | `schemaVersion ∈ accepted set` → published normally. |
| `test_bridge_schema_version_rejected` | 3 | Unknown `schemaVersion` → DLQ `employee.events.dlq.schema`. |
| `test_bridge_employee_id_mismatch_dlq` | 3 | `envelope.employeeId ≠ mqtt.user_id` → DLQ + structured WARNING. |
| `test_bridge_batch_fans_to_per_position` | 3 | `positions: [p1, p2, p3]` → 3 AMQP messages, headers carry `positionIndex`, `batchSize`. |
| `test_bridge_batch_size_one` | 3 | Single-position batch → exactly one downstream message. |
| `test_bridge_batch_oversize_dlq` | 3 | `len(positions) > MQTT_MAX_BATCH_SIZE` → DLQ. |
| `test_bridge_empty_positions_dlq` | 3 | `positions: []` → DLQ. |
| `test_bridge_non_location_routing_keys` | 3 | `events/incidents` → `employee.incident.created`. |
| `test_downlink_publish_routing_key` | 4 | `publish_to_employee("123", "notifications", {...})` → `amq.topic` / `employees.123.notifications`. |
| `test_engine_load_from_db_per_tenant` | 6 | Two tenants, polygons isolated by tenant. |
| `test_engine_evaluate_enter` | 6 | Point inside polygon (not previously inside) → `kind=enter`. |
| `test_engine_evaluate_exit` | 6 | Point outside polygon (previously inside) → `kind=exit`. |
| `test_engine_evaluate_stay_no_transition` | 6 | Two consecutive points inside same polygon → no transition. |
| `test_engine_evaluate_multi_geofence` | 6 | Employee inside two polygons simultaneously → state set tracks both. |
| `test_engine_dwell_timer_fires` | 6 | After `dwell_seconds` continuous presence → `kind=dwell` emitted. |
| `test_engine_dwell_timer_cancelled_on_exit` | 6 | `exit` before timer fires → no `dwell` transition. |
| `test_engine_dwell_per_geofence_override` | 6 | Geofence with `dwell_seconds=60` uses that, not default 300. |
| `test_engine_out_of_order_skipped` | 6 | `ts < last_seen_ts` → skipped (default config). |
| `test_engine_self_intersecting_polygon_rejected` | 9 | CRUD POST with invalid polygon → 422. |
| `test_engine_evaluate_batch_collapses_intra_batch_flaps` | 6 | enter→exit→enter in one batch → single `enter` (when `GEOFENCE_COLLAPSE_INTRA_BATCH=True`). |
| `test_engine_reload_one_atomic` | 6 | Concurrent `reload_one` and `evaluate` → no partial state observed. |
| `test_decorator_filter_geofence_name` | 7 | Handler with `geofence_name="store_42"` fires only for that geofence. |
| `test_decorator_filter_kind` | 7 | Handler with `kind="dwell"` fires only on dwell transitions. |
| `test_decorator_filter_tenant_and_employee` | 7 | Conjunctive filter — all must match. |
| `test_dispatcher_fan_out_concurrency` | 7 | All 5 channels invoked concurrently; one channel slow doesn't block others. |
| `test_dispatcher_handler_timeout` | 7 | Python handler exceeding `GEOFENCE_HANDLER_TIMEOUT` is cancelled; others run. |
| `test_dispatcher_handler_exception_isolated` | 7 | One handler raising doesn't block others; logged, not propagated. |
| `test_dispatcher_webhook_filter_by_tenant` | 7 | Webhook for tenant A is never invoked for a transition in tenant B. |
| `test_webhook_hmac_signature_deterministic` | 8 | Same body + secret → identical signature. |
| `test_webhook_hmac_includes_timestamp_header` | 8 | `X-Navigator-Timestamp` present and recent. |
| `test_fcm_provider_builds_service_account_jwt` | 8 | Signed JWT validates against the provided service-account key. |
| `test_crud_geofence_create_tenant_scoped` | 9 | User in tenant A cannot POST a geofence for tenant B (without admin scope). |
| `test_crud_geofence_update_publishes_changed_event` | 9 | PATCH causes `geofence.changed` fanout publish. |
| `test_crud_webhook_secret_encrypted_at_rest` | 9 | DB row stores ciphertext, not plaintext. |
| `test_mqtt_auth_user_valid_jwt_returns_allow` | 2 | Valid JWT → `allow tags=management`. |
| `test_mqtt_auth_user_invalid_jwt_returns_deny` | 2 | Expired or unsigned JWT → `deny`. |
| `test_mqtt_auth_topic_employee_can_subscribe_own` | 2 | Employee 123 → `mqtt.subscribe:employees.123.#` allowed. |
| `test_mqtt_auth_topic_employee_cannot_subscribe_other` | 2 | Employee 123 → `mqtt.subscribe:employees.456.#` denied. |
| `test_mqtt_auth_topic_admin_scope_broad_access` | 2 | Admin JWT → wildcard allowed. |
| `test_mqtt_auth_cache_hit_avoids_recompute` | 2 | Second identical call within TTL is served from cache. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_mqtt_publish_to_downstream_queue` | Mobile-style MQTT publish → RabbitMQ MQTT plugin → bridge → `employee.events` queue → assertion. |
| `test_end_to_end_geofence_enter_to_mqtt_downlink` | Position publish crosses geofence → dispatcher fans out → MQTT-subscribed test client receives notification on `employees/123/notifications`. |
| `test_end_to_end_dwell_emission` | Continuous-presence simulation → after `dwell_seconds` → `kind=dwell` propagates to all 5 channels. |
| `test_end_to_end_hot_reload_under_load` | While ingesting points, CRUD-update a polygon → `geofence.changed` fans out → in-flight evaluations observe new polygon set. |
| `test_end_to_end_jwt_revocation_drops_connection` | Revoke JWT in `navigator_auth` → next `/mqtt/auth/topic` call returns `deny` → RabbitMQ disconnects client. |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_envelope_batch():
    return {
        "eventId": "11111111-2222-3333-4444-555555555555",
        "employeeId": "123",
        "type": "location.batch",
        "schemaVersion": 1,
        "positions": [
            {"lat": 19.43, "lng": -99.13, "ts": "2026-05-27T10:15:01.220Z"},
            {"lat": 19.44, "lng": -99.14, "ts": "2026-05-27T10:15:06.180Z"},
        ],
    }

@pytest.fixture
def sample_tenant_geofences():
    return [
        Geofence(id=1, tenant_id="acme", name="store_42",
                 polygon='{"type":"Polygon","coordinates":[[[...]]]}',
                 active=True, dwell_seconds=None,
                 created_at=..., updated_at=...),
    ]

@pytest.fixture
async def fake_redis_dedup():
    """In-memory dict masquerading as Redis TTL set for unit tests."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `USE_MQTT_BRIDGE=false` keeps **zero** new modules at import time (lazy loading verified).
- [ ] `EmployeeEventsBridge` dedups by `eventId` and per-position by `{eventId}:{positionIndex}` via Redis TTL set; fails open on Redis downtime.
- [ ] `EmployeeEventsBridge` rejects unknown `schemaVersion` to `employee.events.dlq.schema`; accepts the set in `MQTT_ACCEPTED_SCHEMA_VERSIONS`.
- [ ] `EmployeeEventsBridge` DLQs envelopes where `envelope.employeeId ≠ MQTT username` (JWT `sub`) with structured WARNING log.
- [ ] `EmployeeEventsBridge` fans `positions[]` into one AMQP message per position with `eventId` + `positionIndex` + `batchSize` headers; `len(positions) > MQTT_MAX_BATCH_SIZE` → DLQ; `positions == []` → DLQ.
- [ ] `MQTTDownlinkPublisher.publish_to_employee("123", "notifications", payload)` results in an AMQP message on `amq.topic` with routing key `employees.123.notifications`.
- [ ] `GeofenceEngine.evaluate(...)` returns correct `enter` / `exit` transitions and tracks per-employee `_inside` sets correctly under multi-polygon overlap.
- [ ] `GeofenceEngine` emits a `kind=dwell` transition once an employee has been continuously inside a geofence for `dwell_seconds` (per-geofence) or `GEOFENCE_DWELL_DURATION` (default 300s); the timer is cancelled on `exit`.
- [ ] `GeofenceEngine.evaluate_batch(...)` collapses intra-batch flaps when `GEOFENCE_COLLAPSE_INTRA_BATCH=True` (default); same Python surface is preserved as the v2 Cython migration target.
- [ ] `GeofenceEngine.reload_one(id)` is atomic against concurrent `evaluate(...)` calls (no partially-loaded state observable).
- [ ] Per-tenant R-trees: a polygon for tenant A is never matched against an employee in tenant B.
- [ ] `@on_geofence_event(geofence_name=..., kind=..., employee_id=..., tenant_id=...)` filters are conjunctive; `None` means "any"; one handler exception does not block others; per-handler timeout `GEOFENCE_HANDLER_TIMEOUT` enforced.
- [ ] `NotificationDispatcher.dispatch(...)` fans out concurrently to all five channels (MQTT downlink, FCM, RabbitMQ fanout, HMAC webhooks, Python callbacks); one failing channel does not block others.
- [ ] Webhook POSTs carry `X-Navigator-Signature: sha256=<hex>` (HMAC-SHA256 over canonical JSON) and `X-Navigator-Timestamp: <unix>`; webhook secrets are stored encrypted at rest.
- [ ] FCM provider uses HTTP v1 with a service-account JWT (no SDK dependency). iOS reached via FCM's APNs bridge. **No `aioapns` dependency added.**
- [ ] `/api/v1/geofencing/fences` and `/api/v1/geofencing/webhooks` CRUD endpoints are tenant-scoped; cross-tenant access requires admin scope. Self-intersecting polygons rejected with HTTP 422.
- [ ] Geofence mutations publish `geofence.changed` (fanout); all running instances reload via `reload_one(id)`.
- [ ] `/api/v1/mqtt/auth/{user,vhost,resource,topic}` handlers delegate JWT decode/validation to `navigator_auth` (no parallel JWT logic); respect `MQTT_AUTH_CACHE_TTL` cache; topic ACL enforces `employees.{their_id}.#` subtree restriction; admin scope grants broader access.
- [ ] **No `MQTT_JWT_SECRET` config key exists** (intentional — JWT signing lives in `navigator_auth`).
- [ ] Ops runbook (`docs/ops/rabbitmq-mqtt.md`) documents `rabbitmq_mqtt`, `rabbitmq_web_mqtt`, `rabbitmq_auth_backend_http` enablement, TLS listener on 8883, per-connection rate-limit policies.
- [ ] `examples/brokers/nav_mqtt_bridge.py` and `examples/geofencing/basic_geofence.py` run end-to-end against a local RabbitMQ-with-MQTT-plugin container.
- [ ] All unit tests pass: `pytest tests/brokers/test_mqtt_bridge.py tests/ext/geofencing/ tests/handlers/test_mqtt_auth.py -v`.
- [ ] All public surfaces in §2 have Google-style docstrings + strict type hints.
- [ ] `shapely>=2.0` is the **only** new top-level dependency added to `pyproject.toml` (via `uv add shapely`).

---

## 6. Codebase Contract

### Verified Imports

```python
# Navigator imports — confirmed to exist:
from navigator.brokers.connection import BaseConnection                     # navigator/brokers/connection.py:14
from navigator.brokers.consumer import BrokerConsumer                       # navigator/brokers/consumer.py:6 (verified to exist)
from navigator.brokers.producer import BrokerProducer                       # navigator/brokers/producer.py:16
from navigator.brokers.rabbitmq.connection import RabbitMQConnection        # navigator/brokers/rabbitmq/connection.py:17
from navigator.brokers.rabbitmq.consumer import RMQConsumer                 # navigator/brokers/rabbitmq/consumer.py:19
from navigator.brokers.rabbitmq.producer import RMQProducer                 # navigator/brokers/rabbitmq/producer.py (re-exported via __init__.py)
from navigator.brokers.rabbitmq import RabbitMQConnection, RMQConsumer, RMQProducer  # navigator/brokers/rabbitmq/__init__.py
from navigator.extensions import BaseExtension                              # navigator/extensions.py:23
from navigator.ext.redis import RedisConnection                             # navigator/ext/redis/__init__.py:9
from navigator.conf import rabbitmq_dsn, USE_RABBITMQ, CACHE_URL,           # navigator/conf.py:226, :219, :136
                            BROKER_MANAGER_QUEUE_SIZE                       # navigator/conf.py:227
from navigator.applications.base import BaseApplication                     # used by setup() in BaseConnection / BaseExtension
from navigator.types import WebApp                                          # type alias for aiohttp.web.Application
from navconfig.logging import logging                                       # used throughout brokers (e.g. connection.py:9)

# External dependencies — confirmed in current codebase:
import aiormq                                                                # pyproject.toml: aiormq>=6.8.1
from aiormq.abc import AbstractConnection, AbstractChannel                  # navigator/brokers/rabbitmq/connection.py:9
from datamodel.parsers.json import json_encoder, json_decoder                # navigator/brokers/rabbitmq/connection.py:11
from aiohttp import web                                                      # navigator/brokers/connection.py:8

# External dependencies — to be ADDED via `uv add shapely`:
from shapely.geometry import Point, Polygon, shape                          # NEW (shapely>=2.0)
from shapely.strtree import STRtree                                          # NEW
from shapely.prepared import prep                                            # NEW
from shapely.validation import explain_validity                              # NEW

# navigator_auth — existing module; JWT helpers reused:
from navigator_auth.conf import AUTH_SESSION_OBJECT                          # used in navigator/brokers/producer.py:9
# Concrete JWT helper imports to be confirmed during TASK design; the contract
# is "delegate to navigator_auth's existing helpers — do not duplicate JWT logic."
```

### Existing Class Signatures

```python
# navigator/brokers/connection.py:14-134
class BaseConnection(ABC):
    def __init__(self, *args, credentials: Union[str, dict] = None,
                 timeout: Optional[int] = 5, **kwargs): ...           # :19
    @abstractmethod
    async def connect(self) -> None: ...                               # :56
    @abstractmethod
    async def disconnect(self) -> None: ...                            # :63
    async def ensure_connection(self) -> None: ...                     # :70
    @abstractmethod
    async def publish_message(self, body, queue_name=None, **kwargs) -> None: ...   # :77
    @abstractmethod
    async def consume_messages(self, queue_name, callback, **kwargs) -> None: ...    # :89
    @abstractmethod
    async def process_message(self, body: bytes, properties: Any) -> str: ...        # :101
    async def start(self, app: web.Application) -> None: ...           # :112
    async def stop(self, app: web.Application) -> None: ...            # :115
    def setup(self, app: web.Application = None) -> None: ...          # :119
    #   - sets self.app from BaseApplication.get_app() or raw web.Application
    #   - app.on_startup.append(self.start)
    #   - app.on_shutdown.append(self.stop)
    #   - app[self._name_] = self
```

```python
# navigator/brokers/rabbitmq/connection.py:17-end
class RabbitMQConnection(BaseConnection):
    def __init__(self, credentials=None, timeout=5, **kwargs):         # :21
        self._dsn = credentials if credentials is not None else rabbitmq_dsn   # :27
        self._connection: Optional[AbstractConnection] = None          # :30
        self._channel: Optional[AbstractChannel] = None                # :31
    def get_channel(self) -> Optional[AbstractChannel]: ...            # :33
    async def connect(self) -> None: ...                                # :36 — uses aiormq.connect(dsn)
    async def create_exchange(self, exchange_name, exchange_type='topic',
                              durable=True, **kwargs): ...              # :142
    async def ensure_exchange(self, exchange_name, exchange_type='topic',
                              **kwargs) -> None: ...                    # :175
    async def publish_message(self, body, queue_name, routing_key, **kwargs) -> None: ...   # :186
    async def process_message(self, body: bytes,
                              properties: aiormq.spec.Basic.Properties) -> str: ...   # :238
    def wrap_callback(self, callback,
                      requeue_on_fail=False, max_retries=3) -> Callable: ...   # :279
    async def consume_messages(self, queue_name, callback, prefetch_count=1) -> None: ...   # :356
```

```python
# navigator/brokers/rabbitmq/consumer.py:19
class RMQConsumer(RabbitMQConnection, BrokerConsumer):
    _name_: str = "rabbitmq_consumer"                                  # :25
    def __init__(self, credentials=None, timeout=5, callback=None, **kwargs): ...   # :27
        #   kwargs: routing_key='*', exchange_type='topic',
        #           exchange_name='navigator', queue_name=None
    async def event_subscribe(self, queue_name, callback) -> None: ...  # :66
    async def subscribe_to_events(self, exchange, queue_name, routing_key,
                                  callback, exchange_type='topic', durable=True,
                                  prefetch_count=1, requeue_on_fail=True,
                                  max_retries=3, **kwargs) -> None: ...  # :78
    async def start(self, app: web.Application) -> None: ...            # :127
```

```python
# navigator/brokers/rabbitmq/producer.py
class RMQProducer(BrokerProducer, RabbitMQConnection):
    _name_: str = "rabbitmq_producer"
    def __init__(self, credentials, queue_size=None, num_workers=4, timeout=5, **kwargs): ...
```

```python
# navigator/brokers/producer.py:16
class BrokerProducer(BaseConnection, ABC):
    _name_: str = "broker_producer"                                    # :27
    def __init__(self, credentials, queue_size=None, num_workers=4, timeout=5, **kwargs): ...   # :29
    def setup(self, app: web.Application = None) -> None: ...           # :47
        #   - adds POST /api/v1/broker/{broker_service}/publish_event
        #     route at :64-66 (event_publisher handler, service_auth-decorated)
    async def queue_event(self, body, queue_name, routing_key=None, **kwargs) -> None: ...   # :108
    async def publish_event(self, body, queue_name, **kwargs) -> None: ...   # :134
    @staticmethod
    def service_auth(fn) -> Callable: ...                              # :163 — navigator_session-based
    @service_auth
    async def event_publisher(self, request: web.Request) -> web.Response: ...   # :187
```

```python
# navigator/extensions.py:23-102
class BaseExtension(ABC):
    name: str = None                                                   # :29
    app: WebApp = None                                                  # :30
    on_startup: Optional[Callable] = None                              # :33
    on_shutdown: Optional[Callable] = None                             # :36
    on_cleanup: Optional[Callable] = None                              # :39
    on_context: Optional[Callable] = None                              # :42
    middleware: Optional[Callable] = None                              # :45
    def __init__(self, *args, app_name: str = None, **kwargs): ...     # :47
    def setup(self, app: WebApp) -> WebApp: ...                         # :59
        #   - registers extension into app[self.name] and app.extensions[self.name]
        #   - wires on_startup / on_shutdown / on_cleanup / on_context if callable
        #   - appends middleware to app.middlewares if callable
```

```python
# navigator/ext/redis/__init__.py:9
class RedisConnection(DBConnection):
    name: str = "redis"
    driver: str = "redis"
    timeout: int = 10
    def __init__(self, app_name: str = None, dsn: str = None, **kwargs): ...
        #   defaults self._dsn = CACHE_URL when not provided
```

```python
# navigator/conf.py (relevant excerpts)
USE_RABBITMQ = config.getboolean('USE_RABBITMQ', fallback=False)       # :219
RABBITMQ_HOST = config.get("RABBITMQ_HOST", fallback="localhost")      # :220
RABBITMQ_PORT = config.get("RABBITMQ_PORT", fallback=5672)             # :221
RABBITMQ_USER = config.get("RABBITMQ_USER", fallback="guest")          # :222
RABBITMQ_PASS = config.get("RABBITMQ_PASS", fallback="guest")          # :223
RABBITMQ_VHOST = config.get("RABBITMQ_VHOST", fallback="navigator")    # :224
rabbitmq_dsn = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}"   # :226
BROKER_MANAGER_QUEUE_SIZE = config.getint("BROKER_MANAGER_QUEUE_SIZE", fallback=4)   # :227
CACHE_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{CACHE_DB}"            # :136
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EmployeeEventsBridge` | `RMQConsumer.subscribe_to_events` | inheritance + override `start()` | `navigator/brokers/rabbitmq/consumer.py:78`, `:127` |
| `EmployeeEventsBridge` | `RabbitMQConnection.publish_message` | inherited | `navigator/brokers/rabbitmq/connection.py:186` |
| `EmployeeEventsBridge` | Redis dedup | `redis.asyncio` via `CACHE_URL` / override | `navigator/conf.py:136`; `navigator/ext/redis/__init__.py:9` |
| `MQTTDownlinkPublisher` | `RMQProducer.queue_event` | inherited | `navigator/brokers/producer.py:108` |
| `GeofencingExtension` | `BaseExtension.setup()` | inheritance | `navigator/extensions.py:59` |
| `GeofencingExtension` | `MQTTDownlinkPublisher` | composition | new modules |
| `GeofenceConsumer` | `RMQConsumer.subscribe_to_events` | inheritance | `navigator/brokers/rabbitmq/consumer.py:78` |
| `mqtt_auth.*` handlers | `navigator_auth` JWT helpers + scope registry | function calls | `navigator_auth` package (existing; concrete helper paths to confirm in task) |
| Hot-reload publisher | `RMQProducer.queue_event` (fanout exchange) | composition | `navigator/brokers/producer.py:108` |

### Does NOT Exist (Anti-Hallucination)

**Does NOT exist in the codebase — must be built:**

- ~~`navigator/brokers/mqtt/`~~ — no MQTT transport module (intentionally; Option A uses pure AMQP).
- ~~`navigator/brokers/rabbitmq/bridge.py`~~ — does not exist; **NEW** in Module 3.
- ~~`navigator/brokers/rabbitmq/downlink.py`~~ — does not exist; **NEW** in Module 4.
- ~~`navigator/ext/geofencing/`~~ — directory does not exist; **NEW** package (Modules 5–10).
- ~~`navigator/ext/geofencing/_engine_fast.pyx`~~ — Cython hot-path is a **v2** deliverable; not in scope.
- ~~`navigator/handlers/mqtt_auth.py`~~ — does not exist; **NEW** in Module 2.
- ~~`@on_geofence_event` / `@subscriber` decorator pattern in `navigator/brokers/`~~ — existing consumers take a `callback` callable in their constructor; there is no decorator-based registry today. The decorator is **NEW** in Module 7.
- ~~`USE_MQTT_BRIDGE`, `MQTT_*`, `GEOFENCE_*`, `EMPLOYEE_EVENTS_EXCHANGE`,
  `WEBHOOK_SIGNING_ALGORITHM` config keys~~ — **NEW** in Module 1.
- ~~`geofences` / `webhooks` DB tables~~ — **NEW** migration in Module 5.
- ~~`shapely`, `pyproj`, `aiomqtt`, `paho-mqtt`, `aioapns`~~ — **none** present in `pyproject.toml`. Only `shapely>=2.0` is added in v1; the others are intentionally **not** added.
- ~~`/api/v1/mqtt/auth/*` HTTP routes~~ — do not exist; **NEW** in Module 2.
- ~~`MQTT_JWT_SECRET` config key~~ — **intentionally not introduced**. JWT signing lives in `navigator_auth`; duplicating it would be a security regression.
- ~~Native APNs provider~~ — deferred to v2. v1 dispatcher's `PushProvider` abstraction is shipped so adding `apns.py` later is additive.
- ~~Redis-backed shared `_inside` set~~ — deferred to v2. v1 keeps per-process state.

**Important non-obvious facts:**

- `BackgroundService` at `navigator/background/service/__init__.py` is a **job queue +
  tracker** (used for `BackgroundQueue` / `TaskWrapper` / `JobTracker`) — it is **NOT**
  the long-running broker-consumer pattern. The actual broker-service pattern that
  `RMQConsumer` / `SQSConsumer` / `RedisConsumer` use is `BaseConnection.setup(app)`
  (`navigator/brokers/connection.py:119`), which wires `app.on_startup.append(self.start)`
  and `app.on_shutdown.append(self.stop)` directly. **When the brainstorm says
  "BackgroundService pattern", we mean this aiohttp-signal-handler pattern, not the
  `BackgroundService` class.**
- The **RabbitMQ MQTT plugin auto-translates** between MQTT topics and AMQP topic-exchange
  routing keys: MQTT publish on `employees/123/location` arrives on `amq.topic` with key
  `employees.123.location`; conversely, AMQP publish on `amq.topic` /
  `employees.123.notifications` is delivered to MQTT subscribers. **This is why
  Navigator can do both ingest and downlink without an MQTT client.**
- `RMQConsumer.subscribe_to_events` already accepts arbitrary `exchange` + `routing_key`
  arguments — it can subscribe to `amq.topic` / `employees.#` out of the box.
- The existing `BrokerProducer.event_publisher` POST route at
  `navigator/brokers/producer.py:187` uses `@service_auth` against `navigator_session`
  (server-to-server). Mobile MQTT JWT auth is a **separate** concern handled by the
  RabbitMQ HTTP auth backend (Module 2).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Inheritance over composition for transport**: `EmployeeEventsBridge` extends
  `RMQConsumer`; `MQTTDownlinkPublisher` extends `RMQProducer`. Reuses every line of
  `RabbitMQConnection`'s retry / serialization / reconnect machinery.
- **`BaseExtension` for domain capability**: `GeofencingExtension` is a `BaseExtension`
  (`navigator/extensions.py:23`); `setup(app)` wires lifecycle and registers
  CRUD routes.
- **Lazy module loading**: Shapely + MQTT-plugin-specific code must only import when
  `USE_MQTT_BRIDGE=True`. Use `__getattr__` lazy loaders in `navigator/ext/geofencing/__init__.py`
  for sub-modules with heavy imports.
- **Async-first**: All public methods are `async def`. Any blocking call (e.g.,
  `shapely.geometry.shape(...)` parsing is C-extension and fast, but DB-driven
  `load_from_db` uses the existing async DB layer; FCM HTTP via `aiohttp`).
- **JWT logic delegation**: `/api/v1/mqtt/auth/*` handlers call into `navigator_auth`'s
  helpers. **Do not** introduce a parallel JWT decode path.
- **Single canonical envelope path**: All location ingest flows through `positions[]`;
  there is no `type=location.single` code path. Single-fix messages are batches of 1.
- **Tenant scoping is mandatory**: Every CRUD endpoint, engine evaluation, and webhook
  dispatch filters by `tenant_id`. There is no global / cross-tenant default.
- **Logging**: `self.logger = logging.getLogger(self.__class__.__name__)` per
  `BaseConnection` convention; never `print`.
- **Config**: All new keys appended to `navigator/conf.py` with safe defaults that keep
  the feature **off** until `USE_MQTT_BRIDGE=True`.

### Known Risks / Gotchas

- **`amq.topic` is RabbitMQ's built-in topic exchange.** Do not redeclare it with a
  conflicting type — `ensure_exchange("amq.topic", exchange_type="topic")` is idempotent
  but a wrong type kwarg will error.
- **Per-process `_inside` set causes duplicate transitions across instances.** This is
  the accepted v1 trade-off; downstream audit consumers must dedup on
  `(employee_id, geofence_id, kind, source_event_id)`. v2 adds Redis-backed shared state.
- **Dwell timers are per-process `asyncio.TimerHandle`** — they do **not** survive process
  restarts. A restart during dwell period silently drops the pending `dwell` transition.
  Acceptable in v1; documented.
- **Shapely 2's `STRtree` returns indices, not geometries.** Code that walks query
  results must round-trip through `_polys_by_tenant[tenant_id][idx]`.
- **`shapely.prepared.prep(...)` accelerates point-in-polygon** — build prepared
  geometries once during `load_from_db()`, not on every `evaluate()` call.
- **Redis dedup TTL must cover device retry window + max broker delivery latency.** Default
  10 minutes; bumping `MQTT_EVENT_DEDUP_TTL` is cheap (single SET per message).
- **`rabbitmq_auth_backend_http` returns plain text**, not JSON: `allow tags=...` or
  `deny` literal strings. Do not return `web.json_response(...)` from these handlers.
- **MQTT plugin sets `message.properties.user_id`** to the authenticated MQTT username
  for AMQP republish. The bridge's employee-id enforcement reads from this field — verify
  the plugin version in the runbook ships this behavior (it does as of RabbitMQ 3.12+).
- **FCM service-account JWT must be signed with the project's service-account key.** Do
  not check the key into source; load from a config-provided path / secret reference.
- **Webhook retry backoff is in-process** — if a Navigator instance dies mid-backoff,
  the webhook is lost. Acceptable in v1 (notifications also reach mobile via MQTT
  downlink and FCM); v2 may persist a retry queue.
- **`navigator_auth` scope registry mutation** is the one externally visible change
  outside this feature's tree. Coordinate the scope additions (`mqtt.subscribe:*`,
  `mqtt.publish:*`) with the `navigator_auth` maintainer (Jesus).

### External Dependencies / Config

| Package | Version | Reason |
|---|---|---|
| `shapely` | `>=2.0` | **NEW.** Geometry + R-tree (`STRtree`, `prepared`, `validation`). ~5 MB install; prebuilt wheels. Add via `uv add shapely`. |
| `aiormq` | existing | AMQP transport. Already at `pyproject.toml:71`. |
| `aiohttp` | existing | FCM HTTP v1, HMAC webhook dispatch, `/mqtt/auth/*` handlers. |
| `redis` (asyncio) | existing | `eventId` dedup; via `navigator/ext/redis` and `CACHE_URL`. |
| `PyJWT` | existing (transitive) | JWT validation in MQTT auth — delegated to `navigator_auth`. |
| `aiomqtt` / `paho-mqtt` | **NOT added in v1** | Option A doesn't need an MQTT client. |
| `aioapns` | **NOT added in v1** | iOS via FCM-APNs bridge; native APNs in v2. |

**Config keys to append to `navigator/conf.py`:**

```python
# MQTT bridge (off by default)
USE_MQTT_BRIDGE = config.getboolean('USE_MQTT_BRIDGE', fallback=False)
MQTT_TOPIC_NAMESPACE = config.get('MQTT_TOPIC_NAMESPACE', fallback='employees')
MQTT_AUTH_CACHE_TTL = config.getint('MQTT_AUTH_CACHE_TTL', fallback=60)
MQTT_EVENT_DEDUP_TTL = config.getint('MQTT_EVENT_DEDUP_TTL', fallback=600)
MQTT_EVENT_DEDUP_REDIS_URL = config.get('MQTT_EVENT_DEDUP_REDIS_URL', fallback=CACHE_URL)
MQTT_ACCEPTED_SCHEMA_VERSIONS = set(map(int,
    config.get('MQTT_ACCEPTED_SCHEMA_VERSIONS', fallback='1').split(',')))
MQTT_MAX_BATCH_SIZE = config.getint('MQTT_MAX_BATCH_SIZE', fallback=200)
MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY = config.getboolean(
    'MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY', fallback=True)

# Geofencing
GEOFENCE_RELOAD_EXCHANGE = config.get(
    'GEOFENCE_RELOAD_EXCHANGE', fallback='geofence.changed')
GEOFENCE_COLLAPSE_INTRA_BATCH = config.getboolean(
    'GEOFENCE_COLLAPSE_INTRA_BATCH', fallback=True)
GEOFENCE_DWELL_DURATION = config.getint('GEOFENCE_DWELL_DURATION', fallback=300)
GEOFENCE_HANDLER_TIMEOUT = config.getfloat('GEOFENCE_HANDLER_TIMEOUT', fallback=5.0)
EMPLOYEE_EVENTS_EXCHANGE = config.get(
    'EMPLOYEE_EVENTS_EXCHANGE', fallback='employee.events')
WEBHOOK_SIGNING_ALGORITHM = config.get(
    'WEBHOOK_SIGNING_ALGORITHM', fallback='sha256')

# Intentionally NOT added (per design decisions):
#   MQTT_JWT_SECRET   — JWT lives in navigator_auth, no duplication
#   APNS_*            — APNs is out of v1 scope; iOS via FCM-APNs bridge
```

---

## Worktree Strategy

- **Default isolation**: **`mixed`** — the feature decomposes into 5 streams that map
  to non-overlapping file trees, with two convergence points.
- **Streams (can run in parallel worktrees):**
  1. **Stream A** — Modules 1 + 2 (config + MQTT auth handlers + ops doc).
     Touches: `navigator/conf.py` (append), `navigator/handlers/mqtt_auth.py`,
     `docs/ops/rabbitmq-mqtt.md`. Light coordination with `navigator_auth` for scope
     registry.
  2. **Stream B** — Modules 3 + 4 (bridge + downlink).
     Touches: `navigator/brokers/rabbitmq/bridge.py`, `downlink.py`, and the
     `__init__.py` export edit. Depends only on existing `navigator/brokers/rabbitmq/`
     and `navigator/ext/redis/`.
  3. **Stream C** — Modules 5 + 6 (geofence models + engine + DB migration).
     Touches: `navigator/ext/geofencing/models.py`, `engine.py`, migration file.
     Pure logic; no broker dependency.
  4. **Stream D** — Modules 7 + 8 + 9 (decorators + dispatcher + push/webhooks + CRUD).
     Depends on Streams B (downlink) and C (engine + models) for end-to-end testing.
  5. **Stream E** — Modules 10 + 11 + 12 (extension package wiring + ops examples +
     test integration). Convergence stream — pulls in A/B/C/D and writes the
     end-to-end examples and the runbook polish.
- **Cross-feature dependencies**: None. No in-flight specs in `sdd/specs/` touch
  `navigator/brokers/rabbitmq/`, `navigator/ext/`, `navigator/handlers/`, or
  `navigator/conf.py` in conflicting ways. `aiohttp-navigator-modernization` (FEAT-001)
  touches the app skeleton; `file-interfaces` (FEAT-002) touches `navigator/utils/file/`.
- **Recommended worktree creation**:
  ```bash
  git worktree add -b feat-005-mqtt-rabbitmq-broker \
    .claude/worktrees/feat-005-mqtt-rabbitmq-broker HEAD
  ```
  Then either run sequentially in one worktree (simpler) or split per stream into
  sibling worktrees if multiple developers/agents work in parallel.

---

## 8. Open Questions

- [ ] Exact `navigator_auth` helper function names to import for JWT decode/validation
      and scope checks. The contract is "delegate to existing helpers"; the concrete
      symbols must be confirmed during Module 2 task design. — *Owner: Jesus*
- [ ] DB migration location and tooling (Alembic? raw SQL files?). Module 5 leaves the
      filename and runner up to the task author since the codebase does not yet have a
      visible canonical migration directory in `navigator/`. — *Owner: Jesus*
- [ ] FCM service-account key storage: file path vs `navigator_auth` secret reference?
      Recommendation is the secret-storage primitives, mirroring webhook secrets, but
      needs sign-off. — *Owner: Jesus*
- [ ] Should `GeofencingExtension` instantiate and own `EmployeeEventsBridge` (so a single
      `setup(app)` brings up the whole stack), or should the bridge be a sibling
      `BaseConnection` configured independently? The brainstorm leans toward the former
      for usability; the latter preserves single-responsibility. — *Owner: Jesus*
- [ ] Confirmation of RabbitMQ MQTT plugin version that propagates `user_id` on
      AMQP republish. Documented as "3.12+" — verify against the ops target version.
      — *Owner: ops*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-27 | Jesus Lara | Initial draft from brainstorm (Rounds 1–3 complete) |
