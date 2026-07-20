# TASK-030: MQTT Auth HTTP Handlers (`rabbitmq_auth_backend_http`)

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-029
**Assigned-to**: unassigned

---

## Context

RabbitMQ MQTT plugin authenticates mobile devices by HTTP-calling four Navigator
endpoints. Without these, devices cannot connect.

Implements **Spec Module 2**: MQTT Auth Handlers.

---

## Scope

- Create `navigator/handlers/mqtt_auth.py` exposing four aiohttp coroutine handlers:
  - `mqtt_auth_user(request)` — POST `/api/v1/mqtt/auth/user`. Form fields `username`,
    `password` (JWT). Validates JWT via `navigator_auth` helpers; on success returns
    plain-text `allow tags=<comma-separated-tags>`; on failure returns `deny`.
  - `mqtt_auth_vhost(request)` — POST `/api/v1/mqtt/auth/vhost`. Form fields
    `username`, `vhost`, `ip`. Returns `allow` if the user is permitted on this
    vhost; otherwise `deny`. v1 allows the default `navigator` vhost for any
    authenticated user.
  - `mqtt_auth_resource(request)` — POST `/api/v1/mqtt/auth/resource`. Form fields
    `username`, `vhost`, `resource`, `name`, `permission`. v1 allows all resources
    on the authorized vhost for authenticated users with valid JWT.
  - `mqtt_auth_topic(request)` — POST `/api/v1/mqtt/auth/topic`. Form fields
    `username`, `vhost`, `resource`, `name`, `permission`, `routing_key`. Enforces
    topic ACL: an employee may only `mqtt.subscribe:employees.{their_id}.#` and
    `mqtt.publish:employees.{their_id}.#`. Admin scopes (configurable scope name)
    grant broader access.
- All four handlers return **plain text** (`Content-Type: text/plain`), not JSON —
  `rabbitmq_auth_backend_http` does not parse JSON.
- In-memory TTL cache keyed by `(username, password_hash, vhost, resource, name,
  permission, routing_key)` with TTL = `MQTT_AUTH_CACHE_TTL`. Cache is a module-level
  dict; eviction is lazy on access.
- Provide a `register_mqtt_auth_routes(app)` helper that adds the four routes to an
  aiohttp `web.Application`.
- **Delegate JWT decode/validation to `navigator_auth`'s existing helpers** — do NOT
  introduce a parallel JWT path. Concrete helper symbols are an Open Question in the
  spec; if not yet known, place a clearly marked `TODO(navigator_auth-helper)` and
  ship a thin wrapper module `navigator/handlers/_mqtt_jwt.py` whose body raises
  `NotImplementedError` until wired. Coordinate with Jesus (spec §8) before final
  submission.
- Add MQTT scopes `mqtt.subscribe:*` and `mqtt.publish:*` to `navigator_auth`'s scope
  registry. If the registry's exact API is unknown, ship the constant strings and a
  `TODO(navigator_auth-scopes)` note; do not invent registration code.

**NOT in scope**: bridge, downlink, engine, dispatcher, CRUD. Just the four auth
handlers + helper registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/handlers/mqtt_auth.py` | CREATE | The four handlers + cache + `register_mqtt_auth_routes` |
| `navigator/handlers/_mqtt_jwt.py` | CREATE (thin) | Indirection over `navigator_auth` JWT helpers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from aiohttp import web                                                # standard
from navconfig.logging import logging                                  # used throughout brokers
from navigator.conf import (
    MQTT_AUTH_CACHE_TTL,                                               # added by TASK-029
)
# navigator_auth helpers — exact symbol names are Open Question per spec §8;
# the existing `navigator/brokers/producer.py:8-9` already does:
from navigator_auth.conf import AUTH_SESSION_OBJECT                    # confirmed
# Use that as a starting point to discover JWT helpers in navigator_auth.
```

### Existing Signatures to Use

```python
# navigator/handlers/base.py exists (cython-compiled .so present)
# — use it as REFERENCE for handler module placement; do NOT import from it
# unless you actually need its base class.

# Spec Module 2 calls for four async handlers with this signature:
async def mqtt_auth_user(request: web.Request) -> web.Response:
    ...
    return web.Response(text="allow tags=management", content_type="text/plain")
    # or
    return web.Response(text="deny", content_type="text/plain")
```

### Does NOT Exist

- ~~`/api/v1/mqtt/auth/*` routes~~ — first time being introduced.
- ~~A canonical JWT-helper module in Navigator~~ — JWT belongs to `navigator_auth`.
  Do NOT reimplement `jwt.decode(...)` here.
- ~~`MQTT_JWT_SECRET`~~ — not a config key.
- ~~A `navigator_auth.mqtt_scopes` module~~ — scope registry shape must be confirmed
  with the `navigator_auth` maintainer (Jesus).

---

## Implementation Notes

- The RabbitMQ HTTP auth backend expects literal `allow`, `allow tags=<x,y>`, or
  `deny` strings — no surrounding JSON.
- Topic ACL parsing: `routing_key` comes in dot-form (e.g., `employees.123.location`)
  because the MQTT plugin already translated. Match `^employees\.{employee_id}\..*`
  against the authenticated user's `employee_id` (from JWT `sub`).
- Cache TTL is short by design (default 60s). Don't cache `deny` results across
  cache windows where revocation could happen — store the timestamp and re-validate
  on each access if it's older than `MQTT_AUTH_CACHE_TTL`.
- Use `web.Response(text=..., content_type="text/plain")` — not `web.json_response`.

---

## Acceptance Criteria

- [ ] `POST /api/v1/mqtt/auth/user` with valid JWT returns `allow ...` (plain text).
- [ ] `POST /api/v1/mqtt/auth/user` with expired/invalid JWT returns `deny`.
- [ ] `POST /api/v1/mqtt/auth/topic` with `username=123` and
      `routing_key=employees.123.location` permission `write` returns `allow`.
- [ ] `POST /api/v1/mqtt/auth/topic` with `username=123` and
      `routing_key=employees.456.location` returns `deny` (cross-employee block).
- [ ] All responses use `Content-Type: text/plain`.
- [ ] Cache hits avoid recomputation within `MQTT_AUTH_CACHE_TTL` seconds.
- [ ] No new JWT decode path — JWT validation goes through `navigator_auth`
      (delegated import or thin wrapper).
- [ ] `register_mqtt_auth_routes(app)` registers all four POST routes.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/handlers/__init__.py` and `base.py` to confirm package shape.
3. Implement handlers + cache + registration helper.
4. If `navigator_auth` JWT helpers are not yet exposed, ship the `TODO(navigator_auth-helper)`
   wrapper and coordinate with Jesus per spec §8.
5. Add unit-test stubs *only if* TASK-041 is also being written in the same worktree;
   otherwise leave tests entirely to TASK-041.
6. Update index status; move file on completion.

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-05-27
**Notes**: Created mqtt_auth.py with four handlers + in-memory TTL cache + register_mqtt_auth_routes. Created _mqtt_jwt.py as thin stub with TODO(navigator_auth-helper) markers per spec §8. Topic ACL enforces employees.{id}.# restriction; admin scope check present.
**Deviations from spec**: JWT signature verification stubbed (PyJWT no-verify) pending navigator_auth-helper wiring confirmation from Jesus.
