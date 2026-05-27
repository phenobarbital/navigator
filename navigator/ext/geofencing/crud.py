"""Geofence + Webhook CRUD Endpoints + Hot-Reload Fanout.

Provides ten aiohttp route handlers for managing geofences and webhooks:

Geofence routes:
- ``GET  /api/v1/geofencing/fences``         list (tenant-scoped)
- ``POST /api/v1/geofencing/fences``         create
- ``GET  /api/v1/geofencing/fences/{id}``    read
- ``PATCH /api/v1/geofencing/fences/{id}``   update
- ``DELETE /api/v1/geofencing/fences/{id}``  soft-delete

Webhook routes:
- ``GET  /api/v1/geofencing/webhooks``        list (tenant-scoped)
- ``POST /api/v1/geofencing/webhooks``        create
- ``GET  /api/v1/geofencing/webhooks/{id}``   read
- ``PATCH /api/v1/geofencing/webhooks/{id}``  update
- ``DELETE /api/v1/geofencing/webhooks/{id}`` soft-delete

Every write path publishes a ``geofence.changed`` fanout event so all Navigator
instances can reload their in-memory R-trees.

Tenant Scoping:
    Every request is scoped to the caller's ``tenant_id`` from the
    ``navigator_session`` session object.  Cross-tenant access requires the
    ``geofencing.admin.cross_tenant`` scope in the JWT.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 9.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from aiohttp import web
from shapely.geometry import shape
from shapely.validation import explain_validity
from shapely import wkt as shapely_wkt

from navigator.conf import GEOFENCE_RELOAD_EXCHANGE
from navigator_session import get_session

logger = logging.getLogger(__name__)

# Admin cross-tenant scope name
_ADMIN_SCOPE = "geofencing.admin.cross_tenant"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _validate_polygon(polygon_text: str) -> Optional[str]:
    """Parse and validate a polygon string (GeoJSON or WKT).

    Args:
        polygon_text: Either a GeoJSON geometry string or a WKT polygon.

    Returns:
        ``None`` if valid; an error reason string if invalid.
    """
    geom = None
    # Try GeoJSON first
    try:
        geojson_dict = json.loads(polygon_text)
        geom = shape(geojson_dict)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass

    # Fall back to WKT
    if geom is None:
        try:
            geom = shapely_wkt.loads(polygon_text)
        except Exception as exc:
            return f"Could not parse polygon as GeoJSON or WKT: {exc}"

    validity = explain_validity(geom)
    if validity != "Valid Geometry":
        return validity
    return None


def _validate_webhook_url(url: str) -> Optional[str]:
    """Validate a webhook URL to prevent SSRF attacks.

    Enforces HTTPS-only and blocks private/loopback/reserved IP ranges
    and well-known localhost hostnames.

    Args:
        url: The candidate webhook URL string.

    Returns:
        ``None`` if the URL is valid; an error message string if invalid.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if parsed.scheme != "https":
        return "Webhook URL must use HTTPS"

    host = parsed.hostname or ""
    if not host:
        return "Webhook URL must have a valid hostname"

    # Block common internal hostnames
    blocked_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if host.lower() in blocked_hosts:
        return "Webhook URL must not target localhost"

    # Block IP addresses in private/reserved ranges
    try:
        addr = ipaddress.ip_address(host)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return "Webhook URL must not target private or reserved IP addresses"
    except ValueError:
        pass  # hostname, not a bare IP — acceptable

    return None  # valid


def _has_cross_tenant_scope(session: Any) -> bool:
    """Return True if the session JWT contains the admin cross-tenant scope.

    Args:
        session: Session object from ``navigator_session.get_session``.

    Returns:
        ``True`` if the ``geofencing.admin.cross_tenant`` scope is present.
    """
    try:
        scopes = session.get("scopes", []) or []
        return _ADMIN_SCOPE in scopes
    except Exception:
        return False


def _get_tenant_id(session: Any) -> Optional[str]:
    """Extract the caller's tenant_id from the session.

    Args:
        session: Session object from ``navigator_session.get_session``.

    Returns:
        Tenant ID string or ``None`` if not present.
    """
    try:
        return session.get("tenant_id") or session.get("tenant")
    except Exception:
        return None


async def _require_session(request: web.Request) -> Any:
    """Retrieve and validate the session, raising HTTP 401 if absent.

    Args:
        request: The aiohttp request.

    Returns:
        The session object.

    Raises:
        :exc:`web.HTTPUnauthorized`: If no valid session is found.
    """
    try:
        session = await get_session(request)
    except (ValueError, RuntimeError) as exc:
        raise web.HTTPUnauthorized(reason=str(exc))
    if not session:
        raise web.HTTPUnauthorized(reason="Authentication required")
    return session


async def _publish_reload(
    reload_publisher: Any,
    geofence_id: Any,
    tenant_id: str,
    action: str,
) -> None:
    """Publish a geofence.changed event to the hot-reload fanout exchange.

    Args:
        reload_publisher: An :class:`~navigator.brokers.rabbitmq.RMQProducer`
            instance for the fanout exchange.
        geofence_id: The affected geofence's primary key.
        tenant_id: Tenant scope for the event.
        action: One of ``"created"``, ``"updated"``, ``"deleted"``.
    """
    try:
        await reload_publisher.queue_event(
            {"geofence_id": str(geofence_id), "tenant_id": tenant_id, "action": action},
            queue_name=GEOFENCE_RELOAD_EXCHANGE,
            routing_key="",
        )
    except Exception as exc:
        logger.warning(
            "_publish_reload: failed to publish reload event geofence_id=%s: %s",
            geofence_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Geofence handlers
# ---------------------------------------------------------------------------


class _GeofencingCRUD:
    """Container for geofence + webhook CRUD handlers.

    Instantiated once by :func:`register_geofencing_crud_routes` and closed
    over by the route handlers.

    Args:
        db: asyncdb-compatible DB connection (supports ``fetch_all``,
            ``fetch_one``, ``execute``).
        reload_publisher: :class:`~navigator.brokers.rabbitmq.RMQProducer` for
            the ``geofence.changed`` fanout exchange.
        secret_encrypt: Callable that takes plaintext bytes and returns
            ciphertext bytes (for storing webhook secrets).
        secret_decrypt: Callable that takes ciphertext bytes and returns
            plaintext bytes (unused in CRUD reads, stored for completeness).
    """

    def __init__(
        self,
        db: Any,
        reload_publisher: Any,
        secret_encrypt: Callable[[bytes], bytes],
        secret_decrypt: Callable[[bytes], bytes],
    ) -> None:
        self._db = db
        self._reload_publisher = reload_publisher
        self._encrypt = secret_encrypt
        self._decrypt = secret_decrypt

    # ------------------------------------------------------------------
    # Geofence routes
    # ------------------------------------------------------------------

    async def list_fences(self, request: web.Request) -> web.Response:
        """GET /api/v1/geofencing/fences — list geofences for the caller's tenant.

        Args:
            request: The aiohttp request.

        Returns:
            JSON array of active geofence rows.
        """
        session = await _require_session(request)
        tenant_id = _get_tenant_id(session)
        if not tenant_id:
            raise web.HTTPUnauthorized(reason="tenant_id not found in session")

        rows = await self._db.fetch_all(
            "SELECT id, tenant_id, name, polygon, active, dwell_seconds, "
            "created_at, updated_at "
            "FROM geofences WHERE tenant_id = $1 AND active = TRUE "
            "ORDER BY created_at DESC",
            tenant_id,
        )
        result = [_fence_to_dict(r) for r in (rows or [])]
        return web.json_response(result)

    async def create_fence(self, request: web.Request) -> web.Response:
        """POST /api/v1/geofencing/fences — create a geofence.

        Request body (JSON):
            name (str): Display name.
            polygon (str): GeoJSON geometry string or WKT.
            dwell_seconds (int, optional): Dwell threshold.
            tenant_id (str, optional): Override only allowed with admin scope.

        Returns:
            JSON object of the created geofence (201).

        Raises:
            :exc:`web.HTTPUnprocessableEntity`: If polygon is invalid.
            :exc:`web.HTTPForbidden`: If tenant_id override without admin scope.
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        if not caller_tenant:
            raise web.HTTPUnauthorized(reason="tenant_id not found in session")

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        # Tenant scope
        requested_tenant = body.get("tenant_id", caller_tenant)
        if requested_tenant != caller_tenant and not _has_cross_tenant_scope(session):
            raise web.HTTPForbidden(
                reason=f"Cross-tenant access requires {_ADMIN_SCOPE} scope"
            )
        tenant_id = requested_tenant

        name = body.get("name", "")
        polygon = body.get("polygon", "")
        if not polygon:
            raise web.HTTPUnprocessableEntity(reason="polygon is required")

        polygon_error = _validate_polygon(polygon)
        if polygon_error:
            return web.json_response(
                {"error": "invalid_polygon", "reason": polygon_error}, status=422
            )

        dwell_seconds = body.get("dwell_seconds")
        fence_id = str(uuid.uuid4())
        now = _now_iso()

        await self._db.execute(
            "INSERT INTO geofences (id, tenant_id, name, polygon, active, "
            "dwell_seconds, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, TRUE, $5, $6, $7)",
            fence_id,
            tenant_id,
            name,
            polygon,
            dwell_seconds,
            now,
            now,
        )

        await _publish_reload(self._reload_publisher, fence_id, tenant_id, "created")

        row = {
            "id": fence_id,
            "tenant_id": tenant_id,
            "name": name,
            "polygon": polygon,
            "active": True,
            "dwell_seconds": dwell_seconds,
            "created_at": now,
            "updated_at": now,
        }
        return web.json_response(row, status=201)

    async def get_fence(self, request: web.Request) -> web.Response:
        """GET /api/v1/geofencing/fences/{id} — read a single geofence.

        Args:
            request: The aiohttp request (contains ``{id}`` match).

        Returns:
            JSON object of the geofence row.

        Raises:
            :exc:`web.HTTPNotFound`: If not found.
            :exc:`web.HTTPForbidden`: If cross-tenant without admin scope.
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        fence_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id, name, polygon, active, dwell_seconds, "
            "created_at, updated_at FROM geofences WHERE id = $1",
            fence_id,
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Geofence {fence_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)
        return web.json_response(_fence_to_dict(row))

    async def update_fence(self, request: web.Request) -> web.Response:
        """PATCH /api/v1/geofencing/fences/{id} — update a geofence.

        Only the provided fields are updated.  If ``polygon`` is updated it
        is re-validated.

        Args:
            request: The aiohttp request.

        Returns:
            JSON object of the updated geofence.

        Raises:
            :exc:`web.HTTPUnprocessableEntity`: If the updated polygon is invalid.
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        fence_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id, name, polygon, active, dwell_seconds, "
            "created_at, updated_at FROM geofences WHERE id = $1",
            fence_id,
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Geofence {fence_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        name = body.get("name", row["name"])
        polygon = body.get("polygon", row["polygon"])
        dwell_seconds = body.get("dwell_seconds", row["dwell_seconds"])
        active = body.get("active", row["active"])

        if "polygon" in body:
            polygon_error = _validate_polygon(polygon)
            if polygon_error:
                return web.json_response(
                    {"error": "invalid_polygon", "reason": polygon_error}, status=422
                )

        now = _now_iso()
        await self._db.execute(
            "UPDATE geofences SET name=$1, polygon=$2, dwell_seconds=$3, "
            "active=$4, updated_at=$5 WHERE id=$6",
            name,
            polygon,
            dwell_seconds,
            active,
            now,
            fence_id,
        )

        tenant_id = row["tenant_id"]
        await _publish_reload(self._reload_publisher, fence_id, tenant_id, "updated")

        updated = {
            "id": fence_id,
            "tenant_id": tenant_id,
            "name": name,
            "polygon": polygon,
            "active": active,
            "dwell_seconds": dwell_seconds,
            "created_at": str(row["created_at"]),
            "updated_at": now,
        }
        return web.json_response(updated)

    async def delete_fence(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/geofencing/fences/{id} — soft-delete (active=False).

        Args:
            request: The aiohttp request.

        Returns:
            JSON confirmation (204-style body with 200 status).
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        fence_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id FROM geofences WHERE id = $1", fence_id
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Geofence {fence_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)

        now = _now_iso()
        await self._db.execute(
            "UPDATE geofences SET active=FALSE, updated_at=$1 WHERE id=$2",
            now,
            fence_id,
        )

        tenant_id = row["tenant_id"]
        await _publish_reload(self._reload_publisher, fence_id, tenant_id, "deleted")
        return web.json_response({"id": fence_id, "deleted": True})

    # ------------------------------------------------------------------
    # Webhook routes
    # ------------------------------------------------------------------

    async def list_webhooks(self, request: web.Request) -> web.Response:
        """GET /api/v1/geofencing/webhooks — list webhooks for the caller's tenant.

        Args:
            request: The aiohttp request.

        Returns:
            JSON array of active webhook rows (secret never included).
        """
        session = await _require_session(request)
        tenant_id = _get_tenant_id(session)
        if not tenant_id:
            raise web.HTTPUnauthorized(reason="tenant_id not found in session")

        rows = await self._db.fetch_all(
            "SELECT id, tenant_id, url, geofence_filter, active, "
            "created_at, updated_at "
            "FROM webhooks WHERE tenant_id = $1 AND active = TRUE "
            "ORDER BY created_at DESC",
            tenant_id,
        )
        result = [_webhook_to_dict(r) for r in (rows or [])]
        return web.json_response(result)

    async def create_webhook(self, request: web.Request) -> web.Response:
        """POST /api/v1/geofencing/webhooks — create a webhook.

        Request body (JSON):
            url (str): Callback URL.
            secret (str): Plaintext HMAC secret (encrypted at write time).
            geofence_filter (int, optional): Optional geofence ID filter.
            tenant_id (str, optional): Override only with admin scope.

        Returns:
            JSON object of the created webhook (201). Secret NOT returned.
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        if not caller_tenant:
            raise web.HTTPUnauthorized(reason="tenant_id not found in session")

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        requested_tenant = body.get("tenant_id", caller_tenant)
        if requested_tenant != caller_tenant and not _has_cross_tenant_scope(session):
            raise web.HTTPForbidden(
                reason=f"Cross-tenant access requires {_ADMIN_SCOPE} scope"
            )
        tenant_id = requested_tenant

        url = body.get("url", "")
        if not url:
            raise web.HTTPBadRequest(reason="url is required")

        url_error = _validate_webhook_url(url)
        if url_error:
            return web.Response(status=400, text=url_error)

        secret_plaintext = body.get("secret", "")
        if not secret_plaintext:
            raise web.HTTPBadRequest(reason="secret is required")

        secret_bytes = secret_plaintext.encode("utf-8") if isinstance(secret_plaintext, str) else secret_plaintext
        secret_encrypted: bytes = self._encrypt(secret_bytes)

        geofence_filter = body.get("geofence_filter")
        hook_id = str(uuid.uuid4())
        now = _now_iso()

        await self._db.execute(
            "INSERT INTO webhooks (id, tenant_id, url, secret_encrypted, "
            "geofence_filter, active, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, TRUE, $6, $7)",
            hook_id,
            tenant_id,
            url,
            secret_encrypted,
            geofence_filter,
            now,
            now,
        )

        row = {
            "id": hook_id,
            "tenant_id": tenant_id,
            "url": url,
            "geofence_filter": geofence_filter,
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
        return web.json_response(row, status=201)

    async def get_webhook(self, request: web.Request) -> web.Response:
        """GET /api/v1/geofencing/webhooks/{id} — read a single webhook.

        Secret is NEVER returned.

        Args:
            request: The aiohttp request.

        Returns:
            JSON object of the webhook (without secret).
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        hook_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id, url, geofence_filter, active, "
            "created_at, updated_at FROM webhooks WHERE id = $1",
            hook_id,
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Webhook {hook_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)
        return web.json_response(_webhook_to_dict(row))

    async def update_webhook(self, request: web.Request) -> web.Response:
        """PATCH /api/v1/geofencing/webhooks/{id} — update a webhook.

        If ``secret`` is present in the body it is re-encrypted.

        Args:
            request: The aiohttp request.

        Returns:
            JSON object of the updated webhook (without secret).
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        hook_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id, url, secret_encrypted, geofence_filter, "
            "active, created_at, updated_at FROM webhooks WHERE id = $1",
            hook_id,
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Webhook {hook_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        url = body.get("url", row["url"])
        geofence_filter = body.get("geofence_filter", row["geofence_filter"])
        active = body.get("active", row["active"])
        now = _now_iso()

        # Validate URL if it is being updated
        if "url" in body:
            url_error = _validate_webhook_url(url)
            if url_error:
                return web.Response(status=400, text=url_error)

        secret_encrypted = row["secret_encrypted"]
        if "secret" in body:
            secret_plaintext = body["secret"]
            secret_bytes = secret_plaintext.encode("utf-8") if isinstance(secret_plaintext, str) else secret_plaintext
            secret_encrypted = self._encrypt(secret_bytes)

        await self._db.execute(
            "UPDATE webhooks SET url=$1, secret_encrypted=$2, "
            "geofence_filter=$3, active=$4, updated_at=$5 WHERE id=$6",
            url,
            secret_encrypted,
            geofence_filter,
            active,
            now,
            hook_id,
        )

        updated = {
            "id": hook_id,
            "tenant_id": row["tenant_id"],
            "url": url,
            "geofence_filter": geofence_filter,
            "active": active,
            "created_at": str(row["created_at"]),
            "updated_at": now,
        }
        return web.json_response(updated)

    async def delete_webhook(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/geofencing/webhooks/{id} — soft-delete (active=False).

        Args:
            request: The aiohttp request.

        Returns:
            JSON confirmation.
        """
        session = await _require_session(request)
        caller_tenant = _get_tenant_id(session)
        hook_id = request.match_info["id"]

        row = await self._db.fetch_one(
            "SELECT id, tenant_id FROM webhooks WHERE id = $1", hook_id
        )
        if not row:
            raise web.HTTPNotFound(reason=f"Webhook {hook_id!r} not found")

        _assert_tenant_access(row["tenant_id"], caller_tenant, session)

        now = _now_iso()
        await self._db.execute(
            "UPDATE webhooks SET active=FALSE, updated_at=$1 WHERE id=$2",
            now,
            hook_id,
        )
        return web.json_response({"id": hook_id, "deleted": True})


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _fence_to_dict(row: Any) -> dict:
    """Convert a geofence DB row to a JSON-safe dict.

    Args:
        row: DB row with geofence fields.

    Returns:
        JSON-serialisable dict.
    """
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "name": row["name"],
        "polygon": row["polygon"],
        "active": bool(row["active"]),
        "dwell_seconds": row["dwell_seconds"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _webhook_to_dict(row: Any) -> dict:
    """Convert a webhook DB row to a JSON-safe dict (secret never included).

    Args:
        row: DB row with webhook fields.

    Returns:
        JSON-serialisable dict without ``secret_encrypted``.
    """
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "url": row["url"],
        "geofence_filter": row["geofence_filter"],
        "active": bool(row["active"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _assert_tenant_access(
    row_tenant: str, caller_tenant: Optional[str], session: Any
) -> None:
    """Raise HTTP 403 if the caller cannot access this row's tenant.

    A caller can always access their own tenant.  Cross-tenant access
    requires :data:`_ADMIN_SCOPE`.

    Args:
        row_tenant: The ``tenant_id`` on the DB row.
        caller_tenant: The tenant extracted from the caller's session.
        session: The full session object (for scope checking).

    Raises:
        :exc:`web.HTTPForbidden`: If tenant mismatch without admin scope.
    """
    if str(row_tenant) != str(caller_tenant) and not _has_cross_tenant_scope(session):
        raise web.HTTPForbidden(
            reason=f"Cross-tenant access requires {_ADMIN_SCOPE} scope"
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_geofencing_crud_routes(
    app: web.Application,
    *,
    db: Any,
    reload_publisher: Any,
    secret_encrypt: Callable[[bytes], bytes],
    secret_decrypt: Callable[[bytes], bytes],
) -> None:
    """Register all 10 geofencing CRUD routes on the aiohttp application.

    Args:
        app: The aiohttp :class:`~aiohttp.web.Application`.
        db: asyncdb-compatible DB connection handle (duck-typed; supports
            ``fetch_all``, ``fetch_one``, ``execute``).
        reload_publisher: :class:`~navigator.brokers.rabbitmq.RMQProducer`
            for publishing ``geofence.changed`` fanout events.
        secret_encrypt: Callable ``(plaintext: bytes) -> ciphertext: bytes``
            used to encrypt webhook HMAC secrets at write time.
        secret_decrypt: Callable ``(ciphertext: bytes) -> plaintext: bytes``
            (stored; passed through to webhook loader at dispatch time).

    Example::

        register_geofencing_crud_routes(
            app,
            db=app["asyncdb"],
            reload_publisher=reload_rmq_producer,
            secret_encrypt=encrypt_fn,
            secret_decrypt=decrypt_fn,
        )
    """
    crud = _GeofencingCRUD(
        db=db,
        reload_publisher=reload_publisher,
        secret_encrypt=secret_encrypt,
        secret_decrypt=secret_decrypt,
    )

    app.router.add_get(
        "/api/v1/geofencing/fences", crud.list_fences
    )
    app.router.add_post(
        "/api/v1/geofencing/fences", crud.create_fence
    )
    app.router.add_get(
        "/api/v1/geofencing/fences/{id}", crud.get_fence
    )
    app.router.add_patch(
        "/api/v1/geofencing/fences/{id}", crud.update_fence
    )
    app.router.add_delete(
        "/api/v1/geofencing/fences/{id}", crud.delete_fence
    )
    app.router.add_get(
        "/api/v1/geofencing/webhooks", crud.list_webhooks
    )
    app.router.add_post(
        "/api/v1/geofencing/webhooks", crud.create_webhook
    )
    app.router.add_get(
        "/api/v1/geofencing/webhooks/{id}", crud.get_webhook
    )
    app.router.add_patch(
        "/api/v1/geofencing/webhooks/{id}", crud.update_webhook
    )
    app.router.add_delete(
        "/api/v1/geofencing/webhooks/{id}", crud.delete_webhook
    )

    logger.info(
        "register_geofencing_crud_routes: 10 routes registered on "
        "/api/v1/geofencing/{fences,webhooks}"
    )
