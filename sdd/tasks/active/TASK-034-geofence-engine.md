# TASK-034: GeofenceEngine — Per-Tenant Shapely R-Tree with Dwell Timers

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-029, TASK-033
**Assigned-to**: unassigned

---

## Context

Heart of the geofencing feature. Per-tenant in-memory Shapely R-tree, per-employee
`inside` set for enter/exit detection, per-`(employee, geofence)` dwell timers.
The `evaluate_batch(...)` API is shipped now so a v2 Cython migration is later
additive.

Implements **Spec Module 6**: Geofence Engine.

---

## Scope

Create `navigator/ext/geofencing/engine.py` exporting `GeofenceEngine`:

- State (instance):
  - `_trees: dict[str, STRtree]` — per-tenant R-tree.
  - `_polys_by_tenant: dict[str, list[tuple[int, Polygon, Optional[int]]]]` —
    parallel array indexed by STRtree result index. Holds `(geofence_id, prepared
    polygon, dwell_seconds_override)`.
  - `_prepared_by_tenant: dict[str, list[PreparedGeometry]]` — prepared polygons
    for fast `.contains(point)`.
  - `_inside: dict[str, set[int]]` — per-employee currently-inside geofence ids.
  - `_entered_at: dict[tuple[str, int], datetime]`.
  - `_dwell_timers: dict[tuple[str, int], asyncio.TimerHandle]`.
  - `_last_seen_ts: dict[str, datetime]` — for out-of-order skip.
  - `_load_lock: asyncio.Lock` — gates `load_from_db` / `reload_one` atomicity.
- Construction: `__init__(self, *, db_loader: Callable[[], Awaitable[list[Geofence]]],
  emit: Callable[[GeofenceTransition], Awaitable[None]],
  dwell_default: int = GEOFENCE_DWELL_DURATION,
  collapse_intra_batch: bool = GEOFENCE_COLLAPSE_INTRA_BATCH)`. `db_loader`
  fetches all active geofences (TASK-038/039 wires this); `emit` is the
  dispatcher hook (TASK-037 wires this).
- `async load_from_db(self) -> None`:
  - Calls `db_loader()`; groups results by `tenant_id`.
  - For each tenant: parse polygon via `shapely.geometry.shape(json.loads(p))` if
    GeoJSON, else `shapely.wkt.loads(p)`. Build `STRtree` over the geometries.
    Pre-prepare each with `shapely.prepared.prep(...)`. Build a new
    `(_trees, _polys_by_tenant, _prepared_by_tenant)` triple in local vars, then
    swap into `self.*` atomically under `_load_lock`. **No partial state ever
    visible to `evaluate`.**
- `async reload_one(self, geofence_id: int) -> None`:
  - Fetch the single geofence (or detect deletion); rebuild only that tenant's
    tree (simplest correct implementation — premature optimization to mutate
    in-place is a v2 concern).
- `def evaluate(self, employee_id: str, tenant_id: str, lat: float, lng: float,
  ts: datetime, source_event_id: UUID) -> list[GeofenceTransition]`:
  - Out-of-order guard: if `ts < self._last_seen_ts.get(employee_id, ts)` → return
    `[]`. Else `self._last_seen_ts[employee_id] = ts`.
  - Get tenant tree; if absent → `[]`.
  - `pt = Point(lng, lat)` (shapely is x,y → lng,lat). Query `_trees[tenant_id]`
    for candidate indices; filter with `_prepared_by_tenant[tenant_id][idx]
    .contains(pt)`.
  - Compute `new_inside: set[int]` from confirmed hits.
  - Diff against `self._inside.setdefault(employee_id, set())`:
    - `entered = new_inside - prev`, `exited = prev - new_inside`.
  - For each `gid in entered`: emit `enter` transition + schedule dwell timer
    (`asyncio.get_running_loop().call_later(dwell_seconds_override or
    dwell_default, self._fire_dwell, employee_id, tenant_id, gid, location)`).
    Record `_entered_at[(employee_id, gid)] = ts`.
  - For each `gid in exited`: emit `exit` transition; cancel dwell timer if
    present; pop `_entered_at`.
  - Replace `self._inside[employee_id] = new_inside`.
  - Return list of emitted transitions (caller forwards to `emit`).
- `def evaluate_batch(self, employee_id, tenant_id, positions: list[Position],
  source_event_id) -> list[GeofenceTransition]`:
  - Iterate `positions` in `ts` ascending order, threading the per-employee
    `inside` set through each `evaluate(...)` call.
  - If `collapse_intra_batch=True`: collect transitions per `(geofence_id,
    employee_id)`; if a `(enter, exit, enter)` sequence collapses to a single
    final `enter`, keep only the final. Simplest correct: re-emit only the diff
    between the initial `inside` (pre-batch) and the final `inside` (post-batch).
    (Implementations may go finer-grained but the diff approach satisfies
    `test_engine_evaluate_batch_collapses_intra_batch_flaps`.)
- `def _fire_dwell(self, employee_id, tenant_id, geofence_id, location)`:
  - Builds a `GeofenceTransition(kind="dwell", dwell_duration=<seconds_in>,
    ...)` and `asyncio.create_task(self.emit(transition))`. Removes the timer
    handle. Logs and swallows exceptions (don't crash event loop).

**NOT in scope**: dispatcher fan-out, CRUD, DB layer (this task accepts a
`db_loader` callable; the integrator wires it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/engine.py` | CREATE | `GeofenceEngine` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio, json, logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Optional
from uuid import UUID

from shapely.geometry import Point, Polygon, shape    # shapely>=2.0 (added by TASK-029)
from shapely.strtree import STRtree
from shapely.prepared import prep, PreparedGeometry
from shapely import wkt as shapely_wkt

from navigator.conf import (
    GEOFENCE_DWELL_DURATION, GEOFENCE_COLLAPSE_INTRA_BATCH,
)
from navigator.ext.geofencing.models import (
    Geofence, Position, GeofenceTransition,
)
```

### Existing Signatures to Use

```python
# navigator/ext/geofencing/models.py (TASK-033)
@dataclass(slots=True)
class Position: lat: float; lng: float; ts: datetime

@dataclass(slots=True)
class Geofence:
    id: int; tenant_id: str; name: str; polygon: str; active: bool
    dwell_seconds: Optional[int]; created_at: datetime; updated_at: datetime

@dataclass(slots=True)
class GeofenceTransition:
    employee_id: str; geofence_id: int; tenant_id: str
    kind: Literal["enter","exit","dwell"]
    location: Position; ts: datetime; source_event_id: UUID
    dwell_duration: Optional[int]

# Shapely 2 STRtree API (verified at shapely.strtree.STRtree docs):
#   tree = STRtree(geoms)                                # build
#   indices = tree.query(point, predicate="intersects")  # returns numpy array of indices
#   # use indices to look up the original geometry / metadata in your own list
```

### Does NOT Exist

- ~~`navigator/ext/geofencing/_engine_fast.pyx`~~ — v2 Cython hot-path; NOT in
  this task. Keep `evaluate_batch` pure Python; the API surface is the migration
  contract.
- ~~A Redis-backed `_inside` shared store~~ — v2. Stay per-process.
- ~~Persisted dwell timers~~ — v2. Timers die with the process.
- ~~`GeofenceEngine.publish(...)` or any RabbitMQ coupling~~ — engine knows
  nothing about brokers; it just emits to the `emit` callback.

### Important Non-Obvious Facts

- **Shapely 2's `STRtree.query` returns indices** (a NumPy array) rather than
  geometries. Round-trip through `_polys_by_tenant[tenant_id][int(idx)]` to get
  the `geofence_id`.
- **`shapely.prepared.prep(...)` is the right primitive for repeated
  point-in-polygon** — build once in `load_from_db`, reuse across `evaluate`.
- **Point construction order**: `Point(x, y)` is `Point(lng, lat)`. A common bug
  is swapping these — write a unit test fixture that proves the orientation.
- **`asyncio.TimerHandle.cancel()`** is idempotent and safe to call after the
  timer has already fired; just `.pop(...)` after either path.

---

## Acceptance Criteria

- [ ] `evaluate(...)` emits exactly one `enter` per `(employee, geofence)` crossing
      and one `exit` per leaving — no duplicates while inside.
- [ ] Multi-polygon overlap: `_inside[employee_id]` correctly tracks the full set
      of currently-inside geofences.
- [ ] Per-tenant isolation: a polygon in tenant A is never matched against an
      employee in tenant B.
- [ ] Dwell timer fires after `dwell_seconds_override or
      GEOFENCE_DWELL_DURATION` seconds of continuous presence; produces
      `kind="dwell"` transition with `dwell_duration` populated.
- [ ] Exiting before the dwell timer fires cancels the timer (no `dwell`
      emitted).
- [ ] Per-geofence `dwell_seconds` override is honored.
- [ ] `load_from_db` swap is atomic vs concurrent `evaluate` (use the lock;
      simple proof: spawn `evaluate` and `load_from_db` concurrently and assert
      no partial-state results).
- [ ] `evaluate_batch` with intra-batch enter→exit→enter (and
      `GEOFENCE_COLLAPSE_INTRA_BATCH=True`) yields one final `enter`.
- [ ] Out-of-order `ts` is silently skipped.
- [ ] Module import is cheap when `USE_MQTT_BRIDGE=False` (top-level imports of
      shapely are fine — they're fast — but no DB or asyncio work at import time).

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/ext/geofencing/models.py` (from TASK-033).
3. Skim Shapely 2 STRtree API in the venv: `python -c "from
   shapely.strtree import STRtree; help(STRtree.query)"`.
4. Implement engine.
5. Smoke-import: `python -c "from navigator.ext.geofencing.engine import
   GeofenceEngine; print('ok')"`.
6. Tests deferred to TASK-041.
7. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
