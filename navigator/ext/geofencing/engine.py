"""GeofenceEngine — Per-Tenant Shapely R-Tree with Dwell Timers.

Maintains one :class:`shapely.strtree.STRtree` per tenant in memory.
Provides enter/exit detection by comparing each ``evaluate()`` result
against a per-employee ``_inside`` set.  Schedules per-``(employee, geofence)``
dwell timers using ``asyncio.TimerHandle``.

Design contract (v2 migration target):
    The ``evaluate_batch(...)`` API surface is shipped here as pure Python.
    A v2 Cython hot-path (``_engine_fast.pyx``) can slot in without changing
    callers.  **Do not change this API surface without bumping the spec.**

Thread-safety / atomicity:
    ``load_from_db()`` acquires :attr:`_load_lock` and swaps tree references
    atomically so that concurrent ``evaluate()`` calls never see partial state.
    ``reload_one()`` rebuilds only the affected tenant's tree under the same lock.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 6.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Optional
from uuid import UUID

from shapely import wkt as shapely_wkt
from shapely.geometry import Point, Polygon, shape
from shapely.prepared import PreparedGeometry, prep
from shapely.strtree import STRtree

from navigator.conf import GEOFENCE_COLLAPSE_INTRA_BATCH, GEOFENCE_DWELL_DURATION
from navigator.ext.geofencing.models import Geofence, GeofenceTransition, Position

logger = logging.getLogger(__name__)


class GeofenceEngine:
    """Per-tenant in-memory geofence evaluator with Shapely R-trees.

    Args:
        db_loader: Async callable that fetches all active
            :class:`~navigator.ext.geofencing.models.Geofence` rows from the
            database.  Signature: ``() -> Awaitable[list[Geofence]]``.
        emit: Async callable invoked for each emitted
            :class:`~navigator.ext.geofencing.models.GeofenceTransition`.
            Signature: ``(GeofenceTransition) -> Awaitable[None]``.
        dwell_default: Default dwell duration in seconds when a geofence has
            no per-row ``dwell_seconds`` override.  Defaults to
            ``GEOFENCE_DWELL_DURATION``.
        collapse_intra_batch: When ``True``, ``evaluate_batch()`` collapses
            intra-batch enter→exit→enter flaps to a single final transition.
            Defaults to ``GEOFENCE_COLLAPSE_INTRA_BATCH``.
    """

    def __init__(
        self,
        *,
        db_loader: Callable[[], Awaitable[list[Geofence]]],
        emit: Callable[[GeofenceTransition], Awaitable[None]],
        dwell_default: int = GEOFENCE_DWELL_DURATION,
        collapse_intra_batch: bool = GEOFENCE_COLLAPSE_INTRA_BATCH,
    ) -> None:
        """Initialize GeofenceEngine.

        Args:
            db_loader: Fetches active geofences from the DB.
            emit: Emits a GeofenceTransition to the downstream dispatcher.
            dwell_default: Default dwell duration in seconds.
            collapse_intra_batch: Whether to collapse intra-batch flaps.
        """
        self._db_loader = db_loader
        self._emit = emit
        self._dwell_default = dwell_default
        self._collapse_intra_batch = collapse_intra_batch

        # Per-tenant state — swapped atomically under _load_lock
        # _trees[tenant_id] = STRtree of shapely Polygon objects
        self._trees: dict[str, STRtree] = {}
        # _polys_by_tenant[tenant_id] = [(geofence_id, Polygon, dwell_seconds_override)]
        self._polys_by_tenant: dict[str, list[tuple[str, Polygon, Optional[int]]]] = {}
        # _prepared_by_tenant[tenant_id] = [PreparedGeometry, ...]  (parallel to _polys_by_tenant)
        self._prepared_by_tenant: dict[str, list[PreparedGeometry]] = {}

        # Per-employee state
        self._inside: dict[str, set[str]] = {}         # employee_id → {geofence_id, ...}
        self._entered_at: dict[tuple[str, str], datetime] = {}  # (emp, geo) → ts
        self._dwell_timers: dict[tuple[str, str], asyncio.TimerHandle] = {}
        self._last_seen_ts: dict[str, float] = {}      # employee_id → last seen unix timestamp

        self._load_lock = asyncio.Lock()

        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Polygon parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_polygon(polygon_str: str) -> Optional[Polygon]:
        """Parse a GeoJSON or WKT polygon string into a Shapely Polygon.

        Tries GeoJSON first, then WKT on failure.

        Args:
            polygon_str: GeoJSON or WKT string.

        Returns:
            A :class:`shapely.geometry.Polygon` on success, ``None`` on error.
        """
        try:
            geo = json.loads(polygon_str)
            return shape(geo)
        except (json.JSONDecodeError, Exception):
            pass
        try:
            return shapely_wkt.loads(polygon_str)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Loading / reloading
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Load all active geofences from the database and rebuild R-trees.

        Groups geofences by ``tenant_id``, parses polygons, builds one
        :class:`~shapely.strtree.STRtree` per tenant, pre-prepares geometries,
        and atomically swaps the in-memory trees under :attr:`_load_lock`.

        Skips geofences with un-parseable polygons (logs a WARNING each).
        """
        geofences: list[Geofence] = await self._db_loader()

        # Group by tenant
        by_tenant: dict[str, list[Geofence]] = {}
        for gf in geofences:
            by_tenant.setdefault(gf.tenant_id, []).append(gf)

        new_trees: dict[str, STRtree] = {}
        new_polys: dict[str, list[tuple[int, Polygon, Optional[int]]]] = {}
        new_prep: dict[str, list[PreparedGeometry]] = {}

        for tenant_id, tenant_geofences in by_tenant.items():
            polys: list[tuple[int, Polygon, Optional[int]]] = []
            geom_list: list[Polygon] = []
            prepared_list: list[PreparedGeometry] = []

            for gf in tenant_geofences:
                poly = self._parse_polygon(gf.polygon)
                if poly is None:
                    self.logger.warning(
                        "GeofenceEngine: could not parse polygon for geofence id=%s tenant=%s",
                        gf.id,
                        tenant_id,
                    )
                    continue
                polys.append((gf.id, poly, gf.dwell_seconds))
                geom_list.append(poly)
                prepared_list.append(prep(poly))

            new_trees[tenant_id] = STRtree(geom_list)
            new_polys[tenant_id] = polys
            new_prep[tenant_id] = prepared_list

        async with self._load_lock:
            self._trees = new_trees
            self._polys_by_tenant = new_polys
            self._prepared_by_tenant = new_prep

        self.logger.info(
            "GeofenceEngine: loaded %d tenants, %d geofences",
            len(new_trees),
            len(geofences),
        )

    async def reload_one(self, geofence_id: str) -> None:
        """Reload a single geofence (or handle its deletion).

        Fetches all active geofences and rebuilds only the affected tenant's
        tree.  Simple and correct for v1; in-place tree mutation is a v2
        optimization.

        Args:
            geofence_id: The UUID string ID of the changed geofence.
        """
        # Reload all — we need to find which tenant owns geofence_id.
        # In v1 this is the simplest correct implementation.
        await self.load_from_db()
        self.logger.debug(
            "GeofenceEngine: reload_one(%s) complete (full reload)", geofence_id
        )

    # ------------------------------------------------------------------
    # Point query helpers
    # ------------------------------------------------------------------

    def _query_tenant(
        self, tenant_id: str, point: Point
    ) -> set[str]:
        """Return the set of geofence IDs that contain ``point`` for a tenant.

        Args:
            tenant_id: Tenant identifier.
            point: Shapely Point (``Point(lng, lat)`` ordering).

        Returns:
            Set of ``geofence_id`` UUID strings whose polygons contain the point.
        """
        tree = self._trees.get(tenant_id)
        if tree is None:
            return set()

        polys = self._polys_by_tenant.get(tenant_id, [])
        prepared = self._prepared_by_tenant.get(tenant_id, [])

        # STRtree.query returns numpy array of indices into the original geom_list
        candidate_indices = tree.query(point, predicate="intersects")
        result: set[str] = set()
        for idx in candidate_indices:
            idx_int = int(idx)
            if idx_int < len(prepared) and prepared[idx_int].contains(point):
                geofence_id, _, _ = polys[idx_int]
                result.add(geofence_id)
        return result

    # ------------------------------------------------------------------
    # Dwell timer
    # ------------------------------------------------------------------

    def _schedule_dwell(
        self,
        employee_id: str,
        tenant_id: str,
        geofence_id: str,
        location: Position,
        dwell_seconds: Optional[int],
        source_event_id: UUID,
        ts: datetime,
    ) -> None:
        """Schedule a dwell timer for a ``(employee_id, geofence_id)`` pair.

        Args:
            employee_id: Employee identifier.
            tenant_id: Tenant identifier.
            geofence_id: Geofence UUID string identifier.
            location: GPS fix at entry time.
            dwell_seconds: Per-geofence override; None uses the default.
            source_event_id: UUID of the source MQTT event.
            ts: Entry timestamp.
        """
        key = (employee_id, geofence_id)
        # Cancel any existing timer for this pair
        old_handle = self._dwell_timers.pop(key, None)
        if old_handle is not None:
            old_handle.cancel()

        duration = dwell_seconds if dwell_seconds is not None else self._dwell_default
        try:
            loop = asyncio.get_running_loop()
            handle = loop.call_later(
                duration,
                self._fire_dwell,
                employee_id,
                tenant_id,
                geofence_id,
                location,
                source_event_id,
                ts,
                duration,
            )
            self._dwell_timers[key] = handle
        except RuntimeError:
            self.logger.warning(
                "GeofenceEngine: no running event loop; cannot schedule dwell timer "
                "for employee=%s geofence=%d",
                employee_id,
                geofence_id,
            )

    def _cancel_dwell(self, employee_id: str, geofence_id: str) -> None:
        """Cancel a pending dwell timer for ``(employee_id, geofence_id)``.

        Args:
            employee_id: Employee identifier.
            geofence_id: Geofence UUID string identifier.
        """
        key = (employee_id, geofence_id)
        handle = self._dwell_timers.pop(key, None)
        if handle is not None:
            handle.cancel()

    def _fire_dwell(
        self,
        employee_id: str,
        tenant_id: str,
        geofence_id: str,
        location: Position,
        source_event_id: UUID,
        ts: datetime,
        dwell_duration: int,
    ) -> None:
        """Timer callback: emit a ``kind="dwell"`` transition.

        Called by the event loop after ``dwell_seconds`` of continuous
        presence.  Creates an async task so the emit coroutine runs in the
        event loop.

        Args:
            employee_id: Employee identifier.
            tenant_id: Tenant identifier.
            geofence_id: Geofence UUID string identifier.
            location: GPS fix at entry time.
            source_event_id: Source MQTT event UUID.
            ts: Entry timestamp.
            dwell_duration: Seconds the employee has been inside.
        """
        self._dwell_timers.pop((employee_id, geofence_id), None)
        transition = GeofenceTransition(
            employee_id=employee_id,
            geofence_id=geofence_id,
            tenant_id=tenant_id,
            kind="dwell",
            location=location,
            ts=ts,
            source_event_id=source_event_id,
            dwell_duration=dwell_duration,
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._safe_emit(transition))
        except RuntimeError as exc:
            self.logger.error(
                "GeofenceEngine._fire_dwell: could not schedule emit: %s", exc
            )

    async def _safe_emit(self, transition: GeofenceTransition) -> None:
        """Emit a transition, swallowing exceptions to protect the event loop.

        Args:
            transition: The :class:`GeofenceTransition` to emit.
        """
        try:
            await self._emit(transition)
        except Exception as exc:
            self.logger.error(
                "GeofenceEngine._safe_emit: error emitting transition: %s", exc
            )

    # ------------------------------------------------------------------
    # Employee state eviction helpers
    # ------------------------------------------------------------------

    def evict_employee(self, employee_id: str) -> None:
        """Remove all geofence state for an employee (e.g., after offboarding).

        Cancels any pending dwell timers for the employee and removes all
        per-employee tracking dicts.  Safe to call even if the employee has
        no state.

        Args:
            employee_id: The employee's identifier.
        """
        self._inside.pop(employee_id, None)
        self._entered_at.pop(employee_id, None)
        self._last_seen_ts.pop(employee_id, None)
        # Cancel any pending dwell timers for this employee
        keys_to_remove = [key for key in self._dwell_timers if key[0] == employee_id]
        for key in keys_to_remove:
            handle = self._dwell_timers.pop(key)
            handle.cancel()
        if keys_to_remove:
            self.logger.debug(
                "GeofenceEngine.evict_employee: evicted employee=%s (%d timers cancelled)",
                employee_id,
                len(keys_to_remove),
            )

    def evict_stale_employees(self, max_age_seconds: float = 604800) -> int:
        """Evict employees not seen for longer than ``max_age_seconds``.

        Useful as a periodic cleanup to prevent unbounded growth of the
        per-employee state dicts for employees who stop sending location
        updates (e.g., device offline or employee offboarded).

        Args:
            max_age_seconds: Maximum age in seconds before an employee is
                considered stale and evicted.  Defaults to 7 days (604 800 s).

        Returns:
            Number of employees evicted.
        """
        now = time.time()
        stale = [
            eid
            for eid, last_ts in self._last_seen_ts.items()
            if (now - last_ts) > max_age_seconds
        ]
        for eid in stale:
            self.evict_employee(eid)
        if stale:
            self.logger.info(
                "GeofenceEngine.evict_stale_employees: evicted %d stale employees "
                "(max_age=%.0fs)",
                len(stale),
                max_age_seconds,
            )
        return len(stale)

    # ------------------------------------------------------------------
    # evaluate
    # ------------------------------------------------------------------

    def evaluate(
        self,
        employee_id: str,
        tenant_id: str,
        lat: float,
        lng: float,
        ts: datetime,
        source_event_id: UUID,
    ) -> list[GeofenceTransition]:
        """Evaluate a single GPS fix against the tenant's geofence R-tree.

        Compares the new ``inside`` set against the previous one, emits
        ``enter``/``exit`` transitions, schedules/cancels dwell timers,
        and updates ``_inside``.

        Args:
            employee_id: Employee identifier.
            tenant_id: Tenant identifier.
            lat: GPS latitude.
            lng: GPS longitude.
            ts: Fix timestamp.
            source_event_id: Source MQTT event UUID.

        Returns:
            List of :class:`GeofenceTransition` emitted for this fix.
            Callers should forward these to :attr:`_emit`.
        """
        # Out-of-order guard (compare as unix timestamps for consistency)
        ts_float = ts.timestamp()
        last_ts_float = self._last_seen_ts.get(employee_id)
        if last_ts_float is not None and ts_float < last_ts_float:
            self.logger.debug(
                "GeofenceEngine: out-of-order fix for employee=%s ts=%s — skipping",
                employee_id,
                ts,
            )
            return []
        self._last_seen_ts[employee_id] = ts_float

        # Point: Shapely uses (x=lng, y=lat) ordering
        point = Point(lng, lat)
        new_inside = self._query_tenant(tenant_id, point)
        prev_inside = self._inside.setdefault(employee_id, set())

        entered = new_inside - prev_inside
        exited = prev_inside - new_inside

        transitions: list[GeofenceTransition] = []
        location = Position(lat=lat, lng=lng, ts=ts)

        for gid in entered:
            transition = GeofenceTransition(
                employee_id=employee_id,
                geofence_id=gid,
                tenant_id=tenant_id,
                kind="enter",
                location=location,
                ts=ts,
                source_event_id=source_event_id,
                dwell_duration=None,
            )
            transitions.append(transition)
            self._entered_at[(employee_id, gid)] = ts

            # Look up per-geofence dwell override
            polys = self._polys_by_tenant.get(tenant_id, [])
            dwell_override: Optional[int] = None
            for gf_id_stored, _, dwell_s in polys:
                if gf_id_stored == gid:
                    dwell_override = dwell_s
                    break
            self._schedule_dwell(
                employee_id=employee_id,
                tenant_id=tenant_id,
                geofence_id=gid,
                location=location,
                dwell_seconds=dwell_override,
                source_event_id=source_event_id,
                ts=ts,
            )

        for gid in exited:
            transition = GeofenceTransition(
                employee_id=employee_id,
                geofence_id=gid,
                tenant_id=tenant_id,
                kind="exit",
                location=location,
                ts=ts,
                source_event_id=source_event_id,
                dwell_duration=None,
            )
            transitions.append(transition)
            self._cancel_dwell(employee_id, gid)
            self._entered_at.pop((employee_id, gid), None)

        self._inside[employee_id] = new_inside
        return transitions

    # ------------------------------------------------------------------
    # evaluate_batch
    # ------------------------------------------------------------------

    def evaluate_batch(
        self,
        employee_id: str,
        tenant_id: str,
        positions: list[Position],
        source_event_id: UUID,
    ) -> list[GeofenceTransition]:
        """Evaluate a batch of GPS fixes in chronological order.

        Threads the per-employee ``inside`` set forward through each position.
        When :attr:`_collapse_intra_batch` is ``True``, collapses intra-batch
        enter→exit→enter sequences: only the diff between the initial and final
        ``inside`` sets is returned.

        This is the v2 Cython migration target — keep this API surface stable.

        **Dwell timer side effects:**
        In both collapse and non-collapse modes, intermediate positions schedule
        dwell timers via :meth:`_schedule_dwell`.  If an employee enters a
        geofence in an early position and exits in a later position within the
        same batch, the dwell timer scheduled on entry is correctly cancelled by
        the exit via :meth:`_cancel_dwell`.  However, if collapse mode is active
        and the net result is "entered" (enter in first position, exit, enter
        again in last position), only the final dwell timer remains active — the
        intermediate timers were cancelled on the intermediate exits.  Callers
        relying on dwell-timer timing accuracy should be aware that the timer
        start time is based on the *final* entry position in the batch.

        Args:
            employee_id: Employee identifier.
            tenant_id: Tenant identifier.
            positions: List of :class:`~navigator.ext.geofencing.models.Position`
                objects in ascending ``ts`` order.
            source_event_id: Source MQTT event UUID.

        Returns:
            List of :class:`GeofenceTransition` objects (possibly collapsed).
        """
        if not positions:
            return []

        # Sort by timestamp ascending
        sorted_positions = sorted(positions, key=lambda p: p.ts)

        if not self._collapse_intra_batch:
            # Simple mode: call evaluate() for each position, accumulate
            all_transitions: list[GeofenceTransition] = []
            for pos in sorted_positions:
                transitions = self.evaluate(
                    employee_id=employee_id,
                    tenant_id=tenant_id,
                    lat=pos.lat,
                    lng=pos.lng,
                    ts=pos.ts,
                    source_event_id=source_event_id,
                )
                all_transitions.extend(transitions)
            return all_transitions

        # Collapse mode: capture state before and after the batch
        prev_inside = set(self._inside.get(employee_id, set()))

        # Thread through all positions to update _inside and timers
        for pos in sorted_positions:
            self.evaluate(
                employee_id=employee_id,
                tenant_id=tenant_id,
                lat=pos.lat,
                lng=pos.lng,
                ts=pos.ts,
                source_event_id=source_event_id,
            )

        final_inside = set(self._inside.get(employee_id, set()))

        # Build transitions based on net diff (collapses flaps)
        net_entered = final_inside - prev_inside
        net_exited = prev_inside - final_inside

        final_pos = sorted_positions[-1]
        final_location = Position(lat=final_pos.lat, lng=final_pos.lng, ts=final_pos.ts)

        collapsed: list[GeofenceTransition] = []
        for gid in net_entered:
            collapsed.append(
                GeofenceTransition(
                    employee_id=employee_id,
                    geofence_id=gid,
                    tenant_id=tenant_id,
                    kind="enter",
                    location=final_location,
                    ts=final_pos.ts,
                    source_event_id=source_event_id,
                    dwell_duration=None,
                )
            )
        for gid in net_exited:
            collapsed.append(
                GeofenceTransition(
                    employee_id=employee_id,
                    geofence_id=gid,
                    tenant_id=tenant_id,
                    kind="exit",
                    location=final_location,
                    ts=final_pos.ts,
                    source_event_id=source_event_id,
                    dwell_duration=None,
                )
            )
        return collapsed
