# TASK-035: `@on_geofence_event` Decorator & Handler Registry

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-033
**Assigned-to**: unassigned

---

## Context

Backend developers register Python handlers with
`@on_geofence_event(geofence_name=..., kind=..., employee_id=..., tenant_id=...)`.
The dispatcher (TASK-037) queries this registry on every transition.

Implements part of **Spec Module 7**: decorator + registry.

---

## Scope

Create `navigator/ext/geofencing/decorators.py`:

- Module-level `_REGISTRY: list[tuple[Filter, Callable]]` where
  `Filter = dict[str, Optional[str|int]]` with optional keys
  `geofence_name`, `kind`, `employee_id`, `tenant_id`.
- `def on_geofence_event(*, geofence_name=None, kind=None, employee_id=None,
  tenant_id=None) -> Callable`. Returns a decorator that asserts the wrapped
  callable is a coroutine (`asyncio.iscoroutinefunction(fn)` — raise
  `TypeError` otherwise) and appends `({...filters}, fn)` to `_REGISTRY`.
  The decorated coroutine is returned unchanged.
- `def get_matching_handlers(transition: GeofenceTransition) -> list[Callable]`:
  iterate `_REGISTRY`; a handler matches when every non-`None` filter equals the
  corresponding `transition.*` attribute. `geofence_name` matches by joining
  `transition.geofence_id` to a name — but the engine doesn't carry the name on
  the transition, so the dispatcher will supply a resolved
  `geofence_name` lookup (TASK-037 owns the name resolution). For this task:
  `geofence_name` filtering compares against a `transition.geofence_name`
  attribute **if present**, else against `None`. **Decision**: extend the
  registry helper to accept an optional `geofence_name_resolver:
  Callable[[int], Optional[str]]` argument so the dispatcher can wire in a
  lookup at call time without coupling to the DB layer.
- Provide `def clear_registry() -> None` for tests.

**NOT in scope**: dispatcher (TASK-037), engine, CRUD. Pure registry mechanics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/decorators.py` | CREATE | Registry + decorator + matcher |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal, Optional
from navigator.ext.geofencing.models import GeofenceTransition   # from TASK-033
```

### Existing Signatures to Use

```python
# navigator/ext/geofencing/models.py (TASK-033)
@dataclass(slots=True)
class GeofenceTransition:
    employee_id: str; geofence_id: int; tenant_id: str
    kind: Literal["enter","exit","dwell"]
    # ... etc.
```

### Does NOT Exist

- ~~A `@subscriber` decorator in `navigator/brokers/`~~ — existing brokers take a
  `callback=` callable in their constructor; there is no decorator-based registry
  to copy. Implement this one from scratch.
- ~~`transition.geofence_name`~~ — not on the dataclass. Use the
  resolver-callback pattern documented in Scope.

---

## Acceptance Criteria

- [ ] `@on_geofence_event(kind="enter")` registers a handler that fires only for
      `enter` transitions.
- [ ] Conjunctive filters: a handler with both `geofence_name="store_42"` and
      `kind="dwell"` fires only when both match.
- [ ] `None` filter values mean "any" — `@on_geofence_event()` matches every
      transition.
- [ ] Wrapping a non-coroutine raises `TypeError`.
- [ ] `clear_registry()` empties `_REGISTRY` (test hygiene).
- [ ] `from navigator.ext.geofencing.decorators import on_geofence_event,
      get_matching_handlers, clear_registry` works.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Implement the module (~70 lines).
3. Quick interactive proof:
   ```python
   import asyncio
   from navigator.ext.geofencing.decorators import on_geofence_event, get_matching_handlers, clear_registry
   clear_registry()
   @on_geofence_event(kind="enter")
   async def h(t): pass
   ```
4. Tests deferred to TASK-041.
5. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
