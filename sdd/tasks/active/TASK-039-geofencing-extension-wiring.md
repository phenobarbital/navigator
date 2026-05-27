# TASK-039: GeofencingExtension + GeofenceConsumer Wiring

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-029, TASK-031, TASK-032, TASK-034, TASK-035, TASK-036, TASK-037, TASK-038
**Assigned-to**: unassigned

---

## Context

Convergence task: composes the engine, dispatcher, consumer, downlink, and CRUD
into a single `BaseExtension` that an app can install with `setup(app)`.

Implements **Spec Module 10**: Extension Package & Geofence Consumer.

---

## Scope

Edit `navigator/ext/geofencing/__init__.py` (created empty in TASK-033) to:

- Re-export the public surface:
  ```python
  from .models import Geofence, Position, GeofenceTransition, Webhook
  from .engine import GeofenceEngine
  from .decorators import on_geofence_event, get_matching_handlers
  from .dispatcher import NotificationDispatcher
  ```
- Define `GeofencingExtension(BaseExtension)`:
  - `name = "geofencing"`.
  - `__init__(self, *, app_name=None, app_db=None, fcm_credentials=None,
    secret_encrypt=None, secret_decrypt=None,
    device_token_lookup=None, install_bridge=True, **kwargs)` —
    accepts an optional `install_bridge` so an app that already has another
    `EmployeeEventsBridge` instance can opt out.
  - `setup(app)`:
    - Calls `super().setup(app)`.
    - Instantiates:
      - `MQTTDownlinkPublisher(credentials=rabbitmq_dsn)`.
      - `RMQProducer(credentials=rabbitmq_dsn, broker_service="geofence_reload")`
        used for hot-reload publishes (this is the `reload_publisher` passed to
        CRUD).
      - `FCMProvider(...)` if `fcm_credentials` provided, else `None`.
      - `GeofenceEngine(db_loader=self._load_geofences,
        emit=self._dispatcher.dispatch, ...)`.
      - `NotificationDispatcher(downlink=..., internal_publisher=...,
        fcm=..., webhook_loader=self._load_webhooks,
        webhook_decrypt=secret_decrypt,
        device_token_lookup=device_token_lookup, ...)`.
      - `GeofenceConsumer(RMQConsumer)` — bound to
        `(EMPLOYEE_EVENTS_EXCHANGE, "geofence.consumer", "employee.location.updated")`;
        callback resolves `tenant_id` (cached lookup) and calls
        `engine.evaluate(...)` then forwards transitions to `dispatcher.dispatch`.
      - If `install_bridge=True`: instantiate `EmployeeEventsBridge` and
        call its `setup(app)`.
    - Calls `register_geofencing_crud_routes(app, db=app_db,
      reload_publisher=self._reload_publisher,
      secret_encrypt=secret_encrypt, secret_decrypt=secret_decrypt)`.
    - Hooks `on_startup` (called by `BaseExtension.setup`):
      1. Connect downlink + reload publisher + bridge.
      2. `await engine.load_from_db()`.
      3. Start `GeofenceConsumer` (subscribe to `employee.events` /
         `employee.location.updated`).
      4. Subscribe to `GEOFENCE_RELOAD_EXCHANGE` (fanout) — on receipt, call
         `engine.reload_one(geofence_id)`.
    - Hooks `on_shutdown`:
      1. Cancel pending dwell timers (`engine._dwell_timers.values()`).
      2. Close dispatcher (`await self._dispatcher.aclose()`).
      3. Stop consumers and disconnect publishers.
- Provide private `_load_geofences()` → reads active geofences from `app_db`
  and returns `list[Geofence]`. Private `_load_webhooks(transition)` → returns
  matching webhooks for tenant + optional geofence filter.

**Tenant resolution helper**: a small async LRU-cached lookup
`_resolve_tenant(employee_id) -> str` that hits `navigator_auth` (helper symbol
is an Open Question; ship with a `TODO(navigator_auth-tenant-lookup)` pointing
at the existing `navigator_auth` session/profile API).

**NOT in scope**: ops docs, examples, tests (TASKs 040 + 041).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/__init__.py` | MODIFY | Add `GeofencingExtension`, re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio, logging
from functools import lru_cache
from collections.abc import Awaitable, Callable
from typing import Optional
from aiohttp import web

from navigator.extensions import BaseExtension                            # navigator/extensions.py:23
from navigator.conf import (
    rabbitmq_dsn,
    EMPLOYEE_EVENTS_EXCHANGE, GEOFENCE_RELOAD_EXCHANGE,
)
from navigator.brokers.rabbitmq import (
    RMQConsumer, RMQProducer,
    EmployeeEventsBridge, MQTTDownlinkPublisher,
)
from navigator.ext.geofencing.models import Geofence, Position, GeofenceTransition, Webhook
from navigator.ext.geofencing.engine import GeofenceEngine
from navigator.ext.geofencing.decorators import on_geofence_event, get_matching_handlers
from navigator.ext.geofencing.dispatcher import NotificationDispatcher
from navigator.ext.geofencing.push_providers.fcm import FCMProvider
from navigator.ext.geofencing.crud import register_geofencing_crud_routes
```

### Existing Signatures to Use

```python
# navigator/extensions.py:23-102
class BaseExtension(ABC):
    name: str = None
    on_startup: Optional[Callable] = None
    on_shutdown: Optional[Callable] = None
    on_cleanup: Optional[Callable] = None
    def setup(self, app) -> WebApp: ...   # :59 — wires startup/shutdown if callable
```

### Does NOT Exist

- ~~An existing `navigator/ext/<name>` extension that subscribes to multiple
  brokers + registers HTTP routes + holds a long-running engine~~ — this is
  the first composite extension of its kind. Lean on the `BaseExtension`
  contract (`navigator/extensions.py:23`).
- ~~A `tenant_lookup` helper in `navigator_auth`~~ — exact API is the spec's
  Open Question; the lookup MUST be replaceable (constructor-injected) so the
  extension can ship without depending on a not-yet-confirmed API.

### Important Non-Obvious Facts

- `BaseExtension.on_startup` is bound at class-or-instance level (`callable`
  attribute). Implement as a coroutine method assigned in `__init__`:
  `self.on_startup = self._on_startup_handler`.
- `BaseExtension.setup` only wires the lifecycle callables if they're
  `callable` — make sure to assign them BEFORE calling `super().setup(app)`.

---

## Acceptance Criteria

- [ ] `from navigator.ext.geofencing import GeofencingExtension,
      on_geofence_event, GeofenceTransition` works.
- [ ] `GeofencingExtension(app_db=..., secret_encrypt=..., secret_decrypt=...).setup(app)`
      registers all CRUD routes and the bridge (when `install_bridge=True`).
- [ ] `app.on_startup` ordering: bridge connects → engine loads → consumers
      start. No race: `engine.load_from_db()` completes before the consumer's
      first `evaluate` call.
- [ ] `app.on_shutdown` cancels all dwell timers before closing the dispatcher.
- [ ] `geofence.changed` (fanout) messages drive `engine.reload_one(id)`.
- [ ] When `install_bridge=False`, no `EmployeeEventsBridge` is constructed
      (allows a separate process to own ingest).

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/extensions.py` end-to-end and re-read
   `navigator/ext/redis/__init__.py:9` for shape.
3. Implement the extension (~250 lines including docstrings).
4. Smoke-import.
5. Tests deferred to TASK-041.
6. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
