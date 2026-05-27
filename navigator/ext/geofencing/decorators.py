"""@on_geofence_event Decorator & Handler Registry.

Provides a simple decorator-based registry for in-process Python callbacks
that react to geofence transition events.  Handlers are registered at
module import time and queried by the :class:`NotificationDispatcher`.

Usage::

    from navigator.ext.geofencing.decorators import on_geofence_event

    @on_geofence_event(geofence_name="store_42", kind="enter")
    async def handle_store_entry(transition):
        print(f"Employee {transition.employee_id} entered store_42")

    @on_geofence_event(kind="dwell")
    async def handle_dwell(transition):
        print(f"Employee {transition.employee_id} has been dwelling for {transition.dwell_duration}s")

Filter semantics:
    All filters are conjunctive — a handler fires only when **all** non-``None``
    filters match the corresponding field on the transition.  A ``None`` filter
    value means "any".

Note:
    ``geofence_name`` is not a field on :class:`GeofenceTransition` (which
    only carries ``geofence_id``).  The matcher accepts an optional
    ``geofence_name_resolver`` callable so the dispatcher can wire in a
    ``geofence_id → name`` lookup without coupling the registry to any DB
    layer.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 7.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal, Optional

from navigator.ext.geofencing.models import GeofenceTransition

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Each entry is a tuple of (filters dict, coroutine callable)
# Filters keys: "geofence_name", "kind", "employee_id", "tenant_id"
_REGISTRY: list[tuple[dict, Callable[..., Awaitable]]] = []


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def on_geofence_event(
    *,
    geofence_name: Optional[str] = None,
    kind: Optional[Literal["enter", "exit", "dwell"]] = None,
    employee_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Callable:
    """Register a coroutine as a geofence-event handler.

    Returns a decorator that appends ``(filters, fn)`` to the module-level
    ``_REGISTRY``.  The decorated coroutine is returned unchanged so it can
    also be called directly.

    Args:
        geofence_name: Only fire when the transition's resolved geofence name
            matches this string.  ``None`` means any geofence.
        kind: Only fire for ``"enter"``, ``"exit"``, or ``"dwell"``
            transitions.  ``None`` means any kind.
        employee_id: Only fire for this employee.  ``None`` means any.
        tenant_id: Only fire for this tenant.  ``None`` means any.

    Returns:
        A decorator that validates and registers the wrapped coroutine.

    Raises:
        TypeError: If the decorated callable is not a coroutine function.

    Example::

        @on_geofence_event(kind="enter", tenant_id="acme")
        async def on_enter(transition: GeofenceTransition) -> None:
            ...
    """
    filters: dict = {
        "geofence_name": geofence_name,
        "kind": kind,
        "employee_id": employee_id,
        "tenant_id": tenant_id,
    }

    def decorator(fn: Callable) -> Callable:
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(
                f"@on_geofence_event requires a coroutine function; "
                f"got {fn!r} which is not async"
            )
        _REGISTRY.append((filters, fn))
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def get_matching_handlers(
    transition: GeofenceTransition,
    *,
    geofence_name_resolver: Optional[Callable[[int], Optional[str]]] = None,
) -> list[Callable[..., Awaitable]]:
    """Return all registered handlers whose filters match the given transition.

    Filters are conjunctive: every non-``None`` filter field must equal the
    corresponding attribute on ``transition`` (or the resolved geofence name).
    A ``None`` filter value matches any value.

    Args:
        transition: The :class:`GeofenceTransition` to match against.
        geofence_name_resolver: Optional callable that maps ``geofence_id``
            to a human-readable geofence name.  Required to satisfy
            ``geofence_name`` filters; if ``None`` and a handler has a
            ``geofence_name`` filter, that handler is **not** matched.

    Returns:
        List of coroutine callables whose filters all match.
    """
    matching: list[Callable[..., Awaitable]] = []

    for filters, fn in _REGISTRY:
        if _matches(filters, transition, geofence_name_resolver):
            matching.append(fn)

    return matching


def _matches(
    filters: dict,
    transition: GeofenceTransition,
    geofence_name_resolver: Optional[Callable[[int], Optional[str]]],
) -> bool:
    """Check whether a single handler's filters all match the transition.

    Args:
        filters: Dict with keys ``geofence_name``, ``kind``, ``employee_id``,
            ``tenant_id``.  ``None`` values are wildcards.
        transition: The transition to test.
        geofence_name_resolver: Optional resolver for geofence names.

    Returns:
        ``True`` if all non-``None`` filters match.
    """
    # kind
    if filters["kind"] is not None and filters["kind"] != transition.kind:
        return False

    # employee_id
    if filters["employee_id"] is not None and filters["employee_id"] != transition.employee_id:
        return False

    # tenant_id
    if filters["tenant_id"] is not None and filters["tenant_id"] != transition.tenant_id:
        return False

    # geofence_name
    if filters["geofence_name"] is not None:
        if geofence_name_resolver is None:
            # Cannot resolve name — cannot satisfy the filter
            return False
        resolved_name = geofence_name_resolver(transition.geofence_id)
        if resolved_name != filters["geofence_name"]:
            return False

    return True


# ---------------------------------------------------------------------------
# Test hygiene
# ---------------------------------------------------------------------------


def clear_registry() -> None:
    """Empty the handler registry.

    Intended for use in test teardown to ensure clean state between tests.
    """
    _REGISTRY.clear()
