# TASK-038: Geofence + Webhook CRUD + Hot-Reload Fanout

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-033, TASK-034
**Assigned-to**: unassigned

---

## Context

Admins manage geofences and webhooks through tenant-scoped REST endpoints.
Mutations publish `geofence.changed` on a fanout exchange so every Navigator
instance reloads its in-memory R-tree.

Implements **Spec Module 9**: CRUD Endpoints & Hot Reload.

---

## Scope

Create `navigator/ext/geofencing/crud.py`:

- Five route handlers for geofences:
  - `GET /api/v1/geofencing/fences` (list, tenant-scoped).
  - `POST /api/v1/geofencing/fences` (create, validates polygon via
    `shapely.validation.explain_validity`; 422 on invalid).
  - `GET /api/v1/geofencing/fences/{id}` (read).
  - `PATCH /api/v1/geofencing/fences/{id}` (update; revalidates polygon if changed).
  - `DELETE /api/v1/geofencing/fences/{id}` (soft delete → `active=False`).
- Five for webhooks:
  - `GET /api/v1/geofencing/webhooks` (list, tenant-scoped).
  - `POST /api/v1/geofencing/webhooks` — body must include `url`, `secret`,
    optional `geofence_filter`. **Encrypt `secret` via injected
    `secret_encrypt(plaintext_bytes) -> ciphertext_bytes`** (wire to
    `navigator_auth` primitives in TASK-039).
  - `GET /api/v1/geofencing/webhooks/{id}` (read; **never** returns the
    decrypted secret).
  - `PATCH /api/v1/geofencing/webhooks/{id}` — re-encrypts if `secret` is provided.
  - `DELETE /api/v1/geofencing/webhooks/{id}` (soft delete).
- **Tenant scoping**: derive caller's tenant from `navigator_auth` session
  (consistent with the rest of Navigator's auth pattern); a request can only
  read/mutate rows where `row.tenant_id == caller.tenant_id`. Cross-tenant access
  requires an admin scope (configurable scope name, e.g.,
  `geofencing.admin.cross_tenant`); if the JWT has it, allow any tenant.
- **Hot-reload publishing**: on every successful mutation, call
  `await self._reload_publisher.queue_event(
      {"geofence_id": id, "tenant_id": tenant, "action": "created"|"updated"|"deleted"},
      queue_name=GEOFENCE_RELOAD_EXCHANGE, routing_key="")`. Exchange is fanout;
  declare it once at startup (TASK-039 owns startup).
- `def register_geofencing_crud_routes(app, *, db, reload_publisher,
  secret_encrypt, secret_decrypt) -> None` — registers all 10 routes against an
  aiohttp app. Pass `db` (the existing app DB connection), the reload publisher
  (an `RMQProducer`), and the encrypt/decrypt callables.
- All write paths return JSON; all read paths return JSON; never raw HTML.

**NOT in scope**: dispatcher wiring, extension lifecycle. TASK-039 owns those.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/crud.py` | CREATE | 10 handlers + `register_geofencing_crud_routes` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json, logging
from collections.abc import Awaitable, Callable
from aiohttp import web
from shapely.geometry import shape
from shapely.validation import explain_validity
from shapely import wkt as shapely_wkt

from navigator.conf import GEOFENCE_RELOAD_EXCHANGE
from navigator.ext.geofencing.models import Geofence, Webhook
# navigator_auth session lookup — same pattern used by navigator/brokers/producer.py:7
from navigator_session import get_session
```

### Existing Signatures to Use

```python
# navigator/brokers/producer.py:7
from navigator_session import get_session
# Used as: session = await get_session(request) in producer.py:170

# navigator/brokers/producer.py:108
async def queue_event(self, body, queue_name, routing_key=None, **kwargs) -> None: ...
# Used here to publish geofence.changed.
```

### Does NOT Exist

- ~~A canonical Navigator CRUD scaffolding macro~~ — implement plain aiohttp
  handlers. Pattern follows `navigator/brokers/producer.py:187` (`event_publisher`)
  for shape (`request.json()`, `web.json_response`).
- ~~Secret encryption helpers in this module~~ — injected via constructor.
- ~~A DB ORM layer~~ — use whatever the app's existing DB connection provides
  (the `db` argument is a duck-typed handle; TASK-039 wires it). For this task,
  assume `await db.fetch_all(query, *args)` / `await db.fetch_one(...)` /
  `await db.execute(...)` style; if the actual app DB exposes a different API,
  adapt accordingly.

### Important Non-Obvious Facts

- The polygon `TEXT` column accepts either GeoJSON or WKT — try GeoJSON first
  (`json.loads(...)` then `shape(...)`); fall back to `wkt.loads(...)`. Reject
  with 422 on parse failure or `explain_validity(...) != "Valid Geometry"`.
- A fanout exchange ignores routing key — pass empty string for clarity.
- Soft-delete (`active=False`) over hard `DELETE` so audit / analytics retains
  history; the engine's `load_from_db` filters `active=True`.

---

## Acceptance Criteria

- [ ] Tenant A user listing geofences sees only tenant A rows.
- [ ] Tenant A user attempting to create a geofence with `tenant_id=B` is
      rejected unless they hold the admin cross-tenant scope.
- [ ] Self-intersecting polygon POST → 422 with
      `explain_validity(...)` reason in the response body.
- [ ] Successful POST/PATCH/DELETE publishes `geofence.changed` to the
      configured fanout exchange.
- [ ] Webhook `secret` is encrypted at write time and never returned on GET.
- [ ] All 10 routes registered through `register_geofencing_crud_routes(app, ...)`.
- [ ] All responses are JSON (`web.json_response`).

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Confirm the app's DB connection API by reading `navigator/ext/db/__init__.py`
   and one of the existing handler modules that does DB work.
3. Implement the 10 handlers + registration helper.
4. Smoke-import.
5. Tests deferred to TASK-041.
6. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
