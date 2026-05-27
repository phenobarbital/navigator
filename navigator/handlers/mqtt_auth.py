"""MQTT Auth HTTP Handlers for RabbitMQ ``rabbitmq_auth_backend_http``.

RabbitMQ's MQTT plugin performs HTTP callbacks to authenticate mobile devices
and enforce per-topic ACLs.  These four handlers implement the HTTP backend
contract (``rabbitmq_auth_backend_http``) by delegating JWT
decode/validation to ``navigator_auth`` via :mod:`_mqtt_jwt`.

**Return format**: plain text ``allow [tags=<x,y>]`` or ``deny``.  The
RabbitMQ auth backend does **not** parse JSON — never return
``web.json_response`` from these handlers.

Routes registered by :func:`register_mqtt_auth_routes`:

- ``POST /api/v1/mqtt/auth/user``
- ``POST /api/v1/mqtt/auth/vhost``
- ``POST /api/v1/mqtt/auth/resource``
- ``POST /api/v1/mqtt/auth/topic``

Configuration keys (from :mod:`navigator.conf`):

- ``MQTT_AUTH_CACHE_TTL`` — seconds before a cached decision expires (default 60).
- ``RABBITMQ_VHOST`` — the permitted vhost for authenticated users.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 2.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from aiohttp import web
from cachetools import TTLCache

from navigator.conf import MQTT_AUTH_CACHE_TTL, RABBITMQ_VHOST
from navigator.handlers._mqtt_jwt import (
    decode_mqtt_token,
    extract_employee_id,
    has_admin_scope,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------
# Key: tuple of request discriminators; Value: allow/deny text string
# TTLCache evicts entries automatically after MQTT_AUTH_CACHE_TTL seconds and
# bounds total memory usage to at most 10 000 cached decisions.
_CACHE: TTLCache = TTLCache(maxsize=10_000, ttl=MQTT_AUTH_CACHE_TTL)

# Short TTL for deny decisions — avoids caching stale denies for too long
# while still protecting against brute-force bursts (5 seconds).
_DENY_TTL: int = 5

_DENY = "deny"


def _cache_key(*parts: str) -> tuple:
    """Build a cache key tuple from discriminator parts."""
    return tuple(parts)


def _cache_get(key: tuple) -> Optional[str]:
    """Return the cached response text if still valid, else None.

    Checks both the standard TTL cache and the short deny cache.

    Args:
        key: Cache key tuple.

    Returns:
        Cached response text, or ``None`` on cache miss.
    """
    # Check deny cache first (short TTL)
    deny_entry = _DENY_CACHE.get(key)
    if deny_entry is not None:
        return deny_entry
    return _CACHE.get(key)


def _cache_set(key: tuple, text: str, *, ttl_override: Optional[int] = None) -> None:
    """Store a decision in the cache.

    For deny decisions, pass ``ttl_override=_DENY_TTL`` to use a much shorter
    TTL so that transient auth failures expire quickly.

    Args:
        key: Cache key tuple.
        text: Response text to cache (``"allow ..."`` or ``"deny"``).
        ttl_override: If provided, store with this TTL (seconds) instead of
            the default ``MQTT_AUTH_CACHE_TTL``.  Used for deny responses.
    """
    if ttl_override is not None:
        # TTLCache does not support per-entry TTLs natively; use a separate
        # short-lived cache for deny responses to approximate the behaviour.
        _DENY_CACHE[key] = text
    else:
        _CACHE[key] = text


# Separate short-TTL cache for deny decisions (prevents caching stale denies).
_DENY_CACHE: TTLCache = TTLCache(maxsize=10_000, ttl=_DENY_TTL)


def _password_hash(password: str) -> str:
    """Return a short hex digest of the password for safe cache keying."""
    return hashlib.sha256(password.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def mqtt_auth_user(request: web.Request) -> web.Response:
    """Authenticate an MQTT client by validating the JWT bearer token.

    RabbitMQ sends ``username`` and ``password`` (JWT) as form-encoded body.
    On success returns ``allow tags=management``; on failure returns ``deny``.

    Args:
        request: aiohttp request with form fields ``username`` and ``password``.

    Returns:
        Plain-text ``allow tags=management`` or ``deny``.
    """
    data = await request.post()
    username: str = data.get("username", "")
    password: str = data.get("password", "")

    cache_key = _cache_key("user", username, _password_hash(password))
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("MQTT auth user: cache hit for username=%s", username)
        return web.Response(text=cached, content_type="text/plain")

    try:
        payload = await decode_mqtt_token(password)
    except NotImplementedError:
        logger.warning(
            "MQTT auth user: JWT validation is not wired — denying username=%s. "
            "Wire navigator_auth before enabling MQTT auth in production.",
            username,
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    if payload is None:
        logger.warning("MQTT auth user: invalid/expired JWT for username=%s", username)
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    result = "allow tags=management"
    _cache_set(cache_key, result)
    logger.debug("MQTT auth user: allow for username=%s", username)
    return web.Response(text=result, content_type="text/plain")


async def mqtt_auth_vhost(request: web.Request) -> web.Response:
    """Check whether an authenticated MQTT user may access the given vhost.

    v1: allows any authenticated user on the configured ``RABBITMQ_VHOST``.

    Args:
        request: aiohttp request with form fields ``username``, ``vhost``,
            ``ip``.

    Returns:
        Plain-text ``allow`` or ``deny``.
    """
    data = await request.post()
    username: str = data.get("username", "")
    vhost: str = data.get("vhost", "")
    password: str = data.get("password", "")

    cache_key = _cache_key("vhost", username, _password_hash(password), vhost)
    cached = _cache_get(cache_key)
    if cached is not None:
        return web.Response(text=cached, content_type="text/plain")

    try:
        payload = await decode_mqtt_token(password)
    except NotImplementedError:
        logger.warning(
            "MQTT auth vhost: JWT validation is not wired — denying username=%s.",
            username,
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    if payload is None:
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    # Allow only the configured RabbitMQ vhost (or "/" which some MQTT clients send)
    permitted_vhosts = {RABBITMQ_VHOST, "/"}
    if vhost not in permitted_vhosts:
        logger.warning(
            "MQTT auth vhost: denied vhost=%s for username=%s", vhost, username
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    _cache_set(cache_key, "allow")
    return web.Response(text="allow", content_type="text/plain")


async def mqtt_auth_resource(request: web.Request) -> web.Response:
    """Authorize access to an AMQP resource (queue/exchange).

    v1: all authenticated users with valid JWT and the permitted vhost may
    access any resource on that vhost.

    Args:
        request: aiohttp request with form fields ``username``, ``vhost``,
            ``resource``, ``name``, ``permission``.

    Returns:
        Plain-text ``allow`` or ``deny``.
    """
    data = await request.post()
    username: str = data.get("username", "")
    password: str = data.get("password", "")
    resource: str = data.get("resource", "")
    name: str = data.get("name", "")
    permission: str = data.get("permission", "")

    cache_key = _cache_key(
        "resource", username, _password_hash(password), resource, name, permission
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return web.Response(text=cached, content_type="text/plain")

    try:
        payload = await decode_mqtt_token(password)
    except NotImplementedError:
        logger.warning(
            "MQTT auth resource: JWT validation is not wired — denying username=%s.",
            username,
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    if payload is None:
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    _cache_set(cache_key, "allow")
    return web.Response(text="allow", content_type="text/plain")


async def mqtt_auth_topic(request: web.Request) -> web.Response:
    """Enforce per-topic ACL for MQTT publish/subscribe.

    An employee (JWT ``sub`` == ``username``) may only access topics under
    ``employees.{their_id}.#``.  Admin scope grants broader access.

    The MQTT plugin translates MQTT topic separators ``/`` to ``.`` before
    sending the routing key here.  So ``employees/123/location`` arrives
    as ``employees.123.location``.

    Args:
        request: aiohttp request with form fields ``username``, ``vhost``,
            ``resource``, ``name``, ``permission``, ``routing_key``.

    Returns:
        Plain-text ``allow`` or ``deny``.
    """
    data = await request.post()
    username: str = data.get("username", "")
    password: str = data.get("password", "")
    routing_key: str = data.get("routing_key", "")
    permission: str = data.get("permission", "")  # "read" or "write"

    cache_key = _cache_key(
        "topic", username, _password_hash(password), routing_key, permission
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return web.Response(text=cached, content_type="text/plain")

    try:
        payload = await decode_mqtt_token(password)
    except NotImplementedError:
        logger.warning(
            "MQTT auth topic: JWT validation is not wired — denying username=%s.",
            username,
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    if payload is None:
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    # Admin scope grants unrestricted access
    if has_admin_scope(payload):
        _cache_set(cache_key, "allow")
        return web.Response(text="allow", content_type="text/plain")

    # Employee ACL: may only access employees.{their_id}.#
    employee_id = extract_employee_id(payload)
    if not employee_id:
        logger.warning(
            "MQTT auth topic: no employee_id in JWT for username=%s", username
        )
        _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
        return web.Response(text=_DENY, content_type="text/plain")

    # routing_key comes in dot-form: e.g. "employees.123.location"
    # Pattern: ^employees\.<employee_id>\..*
    pattern = re.compile(r"^employees\." + re.escape(str(employee_id)) + r"(\.|$)")
    if pattern.match(routing_key):
        _cache_set(cache_key, "allow")
        return web.Response(text="allow", content_type="text/plain")

    logger.warning(
        "MQTT auth topic: denied employee_id=%s routing_key=%s permission=%s",
        employee_id,
        routing_key,
        permission,
    )
    _cache_set(cache_key, _DENY, ttl_override=_DENY_TTL)
    return web.Response(text=_DENY, content_type="text/plain")


# ---------------------------------------------------------------------------
# Route registration helper
# ---------------------------------------------------------------------------


def register_mqtt_auth_routes(app: web.Application) -> None:
    """Register the four MQTT auth handler routes on an aiohttp Application.

    Args:
        app: An ``aiohttp.web.Application`` instance.

    Example::

        from navigator.handlers.mqtt_auth import register_mqtt_auth_routes
        register_mqtt_auth_routes(app)
    """
    app.router.add_post("/api/v1/mqtt/auth/user", mqtt_auth_user)
    app.router.add_post("/api/v1/mqtt/auth/vhost", mqtt_auth_vhost)
    app.router.add_post("/api/v1/mqtt/auth/resource", mqtt_auth_resource)
    app.router.add_post("/api/v1/mqtt/auth/topic", mqtt_auth_topic)
    logger.info("MQTT auth routes registered at /api/v1/mqtt/auth/{user,vhost,resource,topic}")
