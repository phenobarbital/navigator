# TASK-033: Geofence Models + DB Migration (`geofences`, `webhooks`)

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-029
**Assigned-to**: unassigned

---

## Context

The engine, CRUD, and dispatcher all rely on the dataclasses defined here and on
the two DB tables. Land this first so the rest of Stream C/D can move.

Implements **Spec Module 5**: Geofence Models & DB Migration.

---

## Scope

- Create `navigator/ext/geofencing/__init__.py` (empty for now — TASK-039 fills it).
- Create `navigator/ext/geofencing/models.py` with the four dataclasses from
  spec §2 "Data Models":
  - `Position(lat, lng, ts)` — `slots=True`.
  - `Geofence(id, tenant_id, name, polygon, active, dwell_seconds, created_at,
    updated_at)` — `slots=True`. `polygon` is a `str` (GeoJSON or WKT).
  - `GeofenceTransition(employee_id, geofence_id, tenant_id, kind, location, ts,
    source_event_id, dwell_duration)` — `slots=True`. `kind` is a `Literal[
    "enter","exit","dwell"]`.
  - `Webhook(id, tenant_id, url, secret_encrypted, geofence_filter, active)` —
    `slots=True`. `secret_encrypted` is `bytes` (decrypted at dispatch).
- Create a SQL migration script (raw SQL is acceptable; spec §8 Open Question
  flags migration tooling as TBD — go with raw SQL named
  `db/migrations/20260527_geofencing.sql` unless the repo already has a different
  canonical layout — check `db/` or `migrations/` at repo root first). Contents:
  ```sql
  CREATE TABLE IF NOT EXISTS geofences (
      id              SERIAL PRIMARY KEY,
      tenant_id       VARCHAR(64) NOT NULL,
      name            VARCHAR(128) NOT NULL,
      polygon         TEXT NOT NULL,           -- GeoJSON or WKT
      active          BOOLEAN NOT NULL DEFAULT TRUE,
      dwell_seconds   INTEGER NULL,             -- per-geofence override; NULL = use GEOFENCE_DWELL_DURATION
      created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_geofences_tenant_active ON geofences (tenant_id, active);

  CREATE TABLE IF NOT EXISTS webhooks (
      id                SERIAL PRIMARY KEY,
      tenant_id         VARCHAR(64) NOT NULL,
      url               TEXT NOT NULL,
      secret_encrypted  BYTEA NOT NULL,
      geofence_filter   INTEGER NULL REFERENCES geofences(id) ON DELETE SET NULL,
      active            BOOLEAN NOT NULL DEFAULT TRUE,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_webhooks_tenant_active ON webhooks (tenant_id, active);
  ```
- If the project uses Alembic or a different migration tool, mirror its style;
  otherwise plain SQL above is acceptable per spec Open Question.

**NOT in scope**: the engine itself, CRUD handlers, dispatcher, secret-encryption
helpers. This task ships only dataclasses + DDL.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/__init__.py` | CREATE | Empty package marker (TASK-039 fills it) |
| `navigator/ext/geofencing/models.py` | CREATE | Four dataclasses |
| `db/migrations/20260527_geofencing.sql` (or project-canonical location) | CREATE | DDL for `geofences` and `webhooks` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID
```

### Existing Signatures to Use

- `navigator/ext/redis/__init__.py:9` and `navigator/ext/db/__init__.py:10` are
  reference shapes for `navigator/ext/<name>/__init__.py` modules. TASK-039 will
  use them; for this task the `__init__.py` is intentionally empty.

### Does NOT Exist

- ~~`navigator/ext/geofencing/`~~ — directory does not exist; create it.
- ~~A `geofences` or `webhooks` SQL table~~ — first migration.
- ~~PostGIS extension~~ — explicitly NOT required; polygons stored as plain TEXT.
- ~~An `ext/geofencing` Alembic env~~ — only create migration tooling if the repo
  already uses it; otherwise plain SQL is per the Open Question default.

---

## Acceptance Criteria

- [ ] `from navigator.ext.geofencing.models import Position, Geofence,
      GeofenceTransition, Webhook` works.
- [ ] All four dataclasses use `slots=True`.
- [ ] `Geofence.dwell_seconds`, `Webhook.geofence_filter`, and
      `GeofenceTransition.dwell_duration` are `Optional[int]`.
- [ ] `GeofenceTransition.kind` is typed as `Literal["enter","exit","dwell"]`.
- [ ] Migration file exists at the documented location; SQL is idempotent
      (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).
- [ ] `tenant_id` is `NOT NULL` on both tables; both have a
      `(tenant_id, active)` index.
- [ ] No PostGIS-specific syntax (no `geometry` columns).

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. `ls db/ migrations/` (repo root) to confirm where migrations live; default
   to `db/migrations/` if neither exists.
3. Create files per Scope.
4. Verify import: `python -c "from navigator.ext.geofencing.models import
   Geofence, Position, GeofenceTransition, Webhook; print('ok')"`.
5. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
