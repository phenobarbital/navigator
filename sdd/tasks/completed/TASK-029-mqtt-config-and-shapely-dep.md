# TASK-029: MQTT/Geofencing Config Keys + shapely Dependency

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task: every later task imports config keys from `navigator/conf.py` and the
geofence engine imports `shapely`. Must land first.

Implements **Spec Module 1**: Configuration & Dependency.

---

## Scope

- Append the config block from spec §7 ("External Dependencies / Config") to
  `navigator/conf.py` immediately after the existing `BROKER_MANAGER_QUEUE_SIZE`
  definition (`navigator/conf.py:227-230`). Keys:
  - `USE_MQTT_BRIDGE` (bool, fallback `False`).
  - `MQTT_TOPIC_NAMESPACE` (`"employees"`), `MQTT_AUTH_CACHE_TTL` (60s),
    `MQTT_EVENT_DEDUP_TTL` (600s), `MQTT_EVENT_DEDUP_REDIS_URL` (falls back to
    `CACHE_URL`), `MQTT_ACCEPTED_SCHEMA_VERSIONS` (parsed from comma-sep, default
    `{1}`), `MQTT_MAX_BATCH_SIZE` (200), `MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY`
    (True).
  - `GEOFENCE_RELOAD_EXCHANGE` (`"geofence.changed"`),
    `GEOFENCE_COLLAPSE_INTRA_BATCH` (True), `GEOFENCE_DWELL_DURATION` (300),
    `GEOFENCE_HANDLER_TIMEOUT` (5.0), `EMPLOYEE_EVENTS_EXCHANGE`
    (`"employee.events"`), `WEBHOOK_SIGNING_ALGORITHM` (`"sha256"`).
- Run `uv add shapely` (must produce `shapely>=2.0`). Verify the resulting
  `pyproject.toml` entry. **No other deps** added (no `aiomqtt`, `paho-mqtt`,
  `aioapns`, `pyproj`).
- **Do NOT** introduce `MQTT_JWT_SECRET` or any `APNS_*` keys — these are
  intentionally excluded per spec §1 (Non-Goals) and §5 (Acceptance Criteria).

**NOT in scope**: any handler, bridge, engine, or extension code. This task is
purely configuration + dependency.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/conf.py` | MODIFY (append) | Add config keys after `BROKER_MANAGER_QUEUE_SIZE` |
| `pyproject.toml` | MODIFY (via `uv add shapely`) | Add `shapely>=2.0` |
| `uv.lock` (if present) | MODIFY (via uv) | Lock file update is automatic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator/conf.py already uses:
from navconfig import config       # verified existing pattern in conf.py
# CACHE_URL is already defined at navigator/conf.py:136
```

### Existing Signatures to Use

```python
# navigator/conf.py
CACHE_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{CACHE_DB}"     # :136
USE_RABBITMQ = config.getboolean('USE_RABBITMQ', fallback=False)  # :219
RABBITMQ_HOST = config.get("RABBITMQ_HOST", fallback="localhost") # :220
# ... lines :221-:226 ...
BROKER_MANAGER_QUEUE_SIZE = config.getint(
    "BROKER_MANAGER_QUEUE_SIZE", fallback=4)                       # :227-:230
# APPEND new keys here.

# Pattern for sets parsed from comma-separated strings (use built-in idiom):
MQTT_ACCEPTED_SCHEMA_VERSIONS = set(map(int,
    config.get('MQTT_ACCEPTED_SCHEMA_VERSIONS', fallback='1').split(',')))
```

### Does NOT Exist

- ~~`MQTT_JWT_SECRET`~~ — intentionally NOT added. JWT lives in `navigator_auth`.
- ~~`APNS_*`~~ — out of v1 scope; iOS via FCM-APNs bridge.
- ~~`shapely`, `pyproj`, `aiomqtt`, `paho-mqtt`, `aioapns`~~ — none in
  `pyproject.toml`. Only `shapely>=2.0` is added by this task.

---

## Acceptance Criteria

- [ ] All config keys from spec §7 appear in `navigator/conf.py` with the documented
      defaults.
- [ ] `MQTT_ACCEPTED_SCHEMA_VERSIONS` is a `set[int]` (not `str` or `list`).
- [ ] `MQTT_EVENT_DEDUP_REDIS_URL` defaults to the existing `CACHE_URL`.
- [ ] `python -c "from navigator.conf import USE_MQTT_BRIDGE, MQTT_MAX_BATCH_SIZE, GEOFENCE_DWELL_DURATION; print(USE_MQTT_BRIDGE, MQTT_MAX_BATCH_SIZE, GEOFENCE_DWELL_DURATION)"` runs with the venv active.
- [ ] `pyproject.toml` has a `shapely>=2.0` entry; `python -c "import shapely; print(shapely.__version__)"` returns a version ≥ 2.
- [ ] No `MQTT_JWT_SECRET` or `APNS_*` keys present.
- [ ] No other new top-level dependencies added.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/conf.py` to locate the insertion point (after line 230).
3. Append the config block; preserve PEP 8.
4. `uv add shapely` to add the dependency.
5. Verify with the acceptance criteria one-liner.
6. Update `sdd/tasks/.index.json` status to `in-progress` → `done` on completion.
7. Move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-05-27
**Notes**: Used `float(config.get(...))` instead of `config.getfloat(...)` because navconfig does not expose `getfloat`. All 14 config keys appended after `BROKER_MANAGER_QUEUE_SIZE`. `shapely>=2.1.2` added via `uv add shapely`.
**Deviations from spec**: Minor: used `float(config.get(..., fallback='5.0'))` for `GEOFENCE_HANDLER_TIMEOUT` instead of `config.getfloat(...)` — navconfig doesn't support `getfloat`.
