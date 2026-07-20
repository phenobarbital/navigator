"""Navigator Geofencing Extension.

Provides MQTT-backed real-time geofencing for Navigator applications.

**Public surface:**

- :class:`GeofencingExtension` — aiohttp extension wiring the full stack.
- :class:`~navigator.ext.geofencing.engine.GeofenceEngine` — in-memory
  Shapely R-tree engine.
- :class:`~navigator.ext.geofencing.dispatcher.NotificationDispatcher` —
  multi-channel fan-out.
- :func:`~navigator.ext.geofencing.decorators.on_geofence_event` — decorator
  for registering in-process handlers.
- Data models: :class:`Geofence`, :class:`Position`,
  :class:`GeofenceTransition`, :class:`Webhook`.

Quick start::

    from navigator.ext.geofencing import GeofencingExtension

    ext = GeofencingExtension(
        app_db=app["asyncdb"],
        secret_encrypt=encrypt_fn,
        secret_decrypt=decrypt_fn,
        device_token_lookup=fetch_device_tokens,
    )
    ext.setup(app)   # registers routes + startup/shutdown hooks

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 10.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from navigator.extensions import BaseExtension
from navigator.conf import (
    rabbitmq_dsn,
    EMPLOYEE_EVENTS_EXCHANGE,
    GEOFENCE_RELOAD_EXCHANGE,
)
from navigator.brokers.rabbitmq import (
    RMQConsumer,
    RMQProducer,
    EmployeeEventsBridge,
    MQTTDownlinkPublisher,
)
from navigator.ext.geofencing.models import Geofence, Position, GeofenceTransition, Webhook
from navigator.ext.geofencing.engine import GeofenceEngine
from navigator.ext.geofencing.decorators import on_geofence_event, get_matching_handlers
from navigator.ext.geofencing.dispatcher import NotificationDispatcher
from navigator.ext.geofencing.push_providers.fcm import FCMProvider
from navigator.ext.geofencing.crud import register_geofencing_crud_routes

__all__ = [
    "GeofencingExtension",
    "GeofenceEngine",
    "NotificationDispatcher",
    "on_geofence_event",
    "get_matching_handlers",
    "Geofence",
    "Position",
    "GeofenceTransition",
    "Webhook",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tenant resolution helper
# ---------------------------------------------------------------------------


async def _resolve_tenant_default(employee_id: str) -> str:  # noqa: ARG001
    """Default tenant resolver — returns 'default'.

    TODO(navigator_auth-tenant-lookup): Replace with a real lookup once the
    ``navigator_auth`` employee-profile API is confirmed.  The injected
    ``tenant_resolver`` constructor parameter allows callers to provide a
    proper implementation without modifying this module.

    Args:
        employee_id: The employee's identifier.

    Returns:
        Tenant ID string.
    """
    return "default"


# ---------------------------------------------------------------------------
# GeofenceConsumer — internal RMQConsumer subclass
# ---------------------------------------------------------------------------


class _GeofenceConsumer(RMQConsumer):
    """RMQConsumer that pipes ``employee.location.updated`` events into the engine.

    Bound to ``EMPLOYEE_EVENTS_EXCHANGE / geofence.consumer /
    employee.location.updated``.

    Args:
        engine: The :class:`GeofenceEngine` to call ``evaluate`` on.
        dispatcher: The :class:`NotificationDispatcher` to dispatch
            transitions to.
        tenant_resolver: Async callable mapping ``employee_id`` to
            ``tenant_id``.
        credentials: RabbitMQ DSN.
    """

    _name_: str = "geofence_consumer"

    def __init__(
        self,
        engine: GeofenceEngine,
        dispatcher: NotificationDispatcher,
        tenant_resolver: Callable[[str], Awaitable[str]],
        credentials: str,
    ) -> None:
        self._engine = engine
        self._dispatcher = dispatcher
        self._tenant_resolver = tenant_resolver
        super().__init__(
            credentials=credentials,
            exchange_name=EMPLOYEE_EVENTS_EXCHANGE,
            queue_name="geofence.consumer",
            routing_key="employee.location.updated",
            exchange_type="topic",
        )

    async def subscriber_callback(self, message: Any, body: Any) -> None:
        """Process an incoming employee location event.

        Args:
            message: Raw aiormq delivered message.
            body: Pre-decoded body (str or dict from wrap_callback).
        """
        try:
            if isinstance(body, str):
                event = json.loads(body)
            else:
                event = body

            employee_id = str(event.get("employee_id", ""))
            lat = float(event.get("lat", event.get("latitude", 0.0)))
            lng = float(event.get("lng", event.get("longitude", 0.0)))
            ts_raw = event.get("ts", event.get("timestamp"))
            source_event_id = event.get("event_id", event.get("id", ""))

            if ts_raw is None:
                ts = datetime.now(tz=timezone.utc)
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = datetime.fromisoformat(str(ts_raw))

            tenant_id = await self._tenant_resolver(employee_id)

            source_uuid = uuid.UUID(str(source_event_id)) if source_event_id else uuid.uuid4()
            transitions = self._engine.evaluate(
                employee_id=employee_id,
                tenant_id=tenant_id,
                lat=lat,
                lng=lng,
                ts=ts,
                source_event_id=source_uuid,
            )
            for transition in transitions:
                await self._dispatcher.dispatch(transition)

        except Exception as exc:
            logger.error(
                "_GeofenceConsumer.subscriber_callback: error processing "
                "employee location event: %s",
                exc,
            )


# ---------------------------------------------------------------------------
# GeofencingExtension
# ---------------------------------------------------------------------------


class GeofencingExtension(BaseExtension):
    """Composite aiohttp extension wiring the full geofencing stack.

    Install this extension to get:

    - In-memory R-tree geofence engine (hot-reloaded on mutations).
    - Multi-channel notification fan-out (MQTT, FCM, RabbitMQ, webhooks,
      Python handlers).
    - CRUD REST API (10 routes at ``/api/v1/geofencing/...``).
    - RabbitMQ consumer for ``employee.location.updated`` events.
    - Optional MQTT ingest bridge (``EmployeeEventsBridge``).

    Args:
        app_name: Extension registration name (default ``"geofencing"``).
        app_db: asyncdb-compatible DB connection handle (duck-typed; supports
            ``fetch_all``, ``fetch_one``, ``execute``).
        fcm_credentials: Optional dict with ``service_account_path`` and
            ``project_id`` for FCM push notifications.  When ``None``, FCM
            channel is skipped.
        secret_encrypt: Callable ``(plaintext: bytes) -> ciphertext: bytes``
            for encrypting webhook secrets.
        secret_decrypt: Callable ``(ciphertext: bytes) -> plaintext: bytes``
            for decrypting webhook secrets.
        device_token_lookup: Async callable mapping ``employee_id`` to a list
            of FCM device registration tokens.
        tenant_resolver: Optional async callable mapping ``employee_id`` to
            ``tenant_id``.  If omitted, a stub returning ``"default"`` is used
            (see :func:`_resolve_tenant_default` TODO).
        install_bridge: If ``True`` (default), instantiate
            :class:`~navigator.brokers.rabbitmq.EmployeeEventsBridge` to
            ingest raw MQTT → AMQP events.  Set ``False`` if another process
            owns the ingest side.

    Example::

        ext = GeofencingExtension(
            app_db=app["asyncdb"],
            secret_encrypt=encrypt_fn,
            secret_decrypt=decrypt_fn,
            device_token_lookup=fetch_device_tokens,
            install_bridge=True,
        )
        ext.setup(app)
    """

    name: str = "geofencing"

    def __init__(
        self,
        *,
        app_name: Optional[str] = None,
        app_db: Any = None,
        fcm_credentials: Optional[dict] = None,
        secret_encrypt: Optional[Callable[[bytes], bytes]] = None,
        secret_decrypt: Optional[Callable[[bytes], bytes]] = None,
        device_token_lookup: Optional[Callable[[str], Awaitable[list]]] = None,
        tenant_resolver: Optional[Callable[[str], Awaitable[str]]] = None,
        install_bridge: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialise the extension.

        Args:
            app_name: Override the extension name in app context.
            app_db: asyncdb-compatible DB connection.
            fcm_credentials: Optional FCM service-account credentials dict.
            secret_encrypt: Callable to encrypt webhook secrets.
            secret_decrypt: Callable to decrypt webhook secrets.
            device_token_lookup: Async callable resolving FCM device tokens.
            tenant_resolver: Async callable resolving tenant for employee.
            install_bridge: Whether to install EmployeeEventsBridge.
            **kwargs: Passed through to BaseExtension.
        """
        super().__init__(app_name=app_name, **kwargs)

        self._app_db = app_db
        self._fcm_credentials = fcm_credentials
        if secret_encrypt is None:
            logger.warning(
                "GeofencingExtension: no secret_encrypt callable provided. "
                "Webhook HMAC secrets will be stored in plaintext. "
                "Provide a secret_encrypt function for production use."
            )
            self._secret_encrypt: Callable[[bytes], bytes] = lambda x: x
        else:
            self._secret_encrypt = secret_encrypt
        self._secret_decrypt = secret_decrypt or (lambda x: x)
        async def _noop_token_lookup(employee_id: str) -> list:
            return []

        self._device_token_lookup = device_token_lookup or _noop_token_lookup
        self._tenant_resolver: Callable[[str], Awaitable[str]] = (
            tenant_resolver or _resolve_tenant_default
        )
        self._install_bridge = install_bridge

        # Components (initialised in setup)
        self._downlink: Optional[MQTTDownlinkPublisher] = None
        self._reload_publisher: Optional[RMQProducer] = None
        self._internal_publisher: Optional[RMQProducer] = None
        self._fcm: Optional[FCMProvider] = None
        self._engine: Optional[GeofenceEngine] = None
        self._dispatcher: Optional[NotificationDispatcher] = None
        self._geo_consumer: Optional[_GeofenceConsumer] = None
        self._reload_consumer: Optional[RMQConsumer] = None
        self._bridge: Optional[EmployeeEventsBridge] = None

        # Wire lifecycle hooks BEFORE calling super().setup() so the base
        # class registers them with the aiohttp app.
        self.on_startup = self._on_startup_handler
        self.on_shutdown = self._on_shutdown_handler

    def setup(self, app: Any) -> Any:
        """Set up the extension on the aiohttp application.

        Instantiates all components, registers CRUD routes, and wires
        startup/shutdown lifecycle hooks.

        Args:
            app: The aiohttp :class:`~aiohttp.web.Application` (or
                :class:`~navigator.applications.base.BaseApplication`).

        Returns:
            The underlying aiohttp application.
        """
        # Build FCM provider if credentials supplied
        if self._fcm_credentials:
            self._fcm = FCMProvider(
                service_account_path=self._fcm_credentials["service_account_path"],
                project_id=self._fcm_credentials["project_id"],
            )

        # Build RabbitMQ producers
        self._downlink = MQTTDownlinkPublisher(credentials=rabbitmq_dsn)
        self._reload_publisher = RMQProducer(
            credentials=rabbitmq_dsn,
            broker_service="geofence_reload",
        )
        self._internal_publisher = RMQProducer(
            credentials=rabbitmq_dsn,
            broker_service="geofence_notifications",
        )

        # Build dispatcher (engine built later since it needs dispatch reference)
        # Use a forward reference trick: dispatcher is built first with a
        # placeholder; engine is built second.
        # Actually: engine needs `emit` = dispatcher.dispatch, but dispatcher
        # needs engine via webhook_loader. Engine is independent of dispatcher
        # for its emit callback — we pass the method reference directly.

        self._dispatcher = NotificationDispatcher(
            downlink=self._downlink,
            internal_publisher=self._internal_publisher,
            fcm=self._fcm,
            webhook_loader=self._load_webhooks,
            webhook_decrypt=self._secret_decrypt,
            device_token_lookup=self._device_token_lookup,
        )

        self._engine = GeofenceEngine(
            db_loader=self._load_geofences,
            emit=self._dispatcher.dispatch,
        )

        self._geo_consumer = _GeofenceConsumer(
            engine=self._engine,
            dispatcher=self._dispatcher,
            tenant_resolver=self._tenant_resolver,
            credentials=rabbitmq_dsn,
        )

        self._reload_consumer = RMQConsumer(
            credentials=rabbitmq_dsn,
            exchange_name=GEOFENCE_RELOAD_EXCHANGE,
            queue_name="geofence.reload",
            routing_key="",
            exchange_type="fanout",
        )
        # Override reload consumer callback inline
        self._reload_consumer.subscriber_callback = self._on_reload_message  # type: ignore[assignment]

        if self._install_bridge:
            self._bridge = EmployeeEventsBridge(credentials=rabbitmq_dsn)

        # Register CRUD routes
        register_geofencing_crud_routes(
            app if hasattr(app, "router") else getattr(app, "app", app),
            db=self._app_db,
            reload_publisher=self._reload_publisher,
            secret_encrypt=self._secret_encrypt,
            secret_decrypt=self._secret_decrypt,
        )

        return super().setup(app)

    # ------------------------------------------------------------------
    # Lifecycle handlers
    # ------------------------------------------------------------------

    async def _on_startup_handler(self, app: Any) -> None:
        """Startup handler: connect producers/consumers, load engine, start consuming.

        Order:
        1. Connect downlink, reload publisher, internal publisher.
        2. Start bridge (if installed).
        3. Load geofences into engine (must complete before first evaluate).
        4. Start geofence consumer.
        5. Start reload consumer.

        Args:
            app: The aiohttp application (passed by aiohttp signal dispatch).
        """
        logger.info("GeofencingExtension: starting up")

        # 1. Connect producers
        await self._downlink.start(app)
        await self._reload_publisher.start(app)
        await self._internal_publisher.start(app)

        # 2. Start bridge
        if self._bridge is not None:
            await self._bridge.start(app)

        # 3. Load geofences (blocking — must complete before consumers start)
        await self._engine.load_from_db()
        logger.info("GeofencingExtension: geofence engine loaded")

        # 4. Start geofence location consumer
        await self._geo_consumer.start(app)

        # 5. Start reload fanout consumer
        await self._reload_consumer.start(app)

        logger.info("GeofencingExtension: startup complete")

    async def _on_shutdown_handler(self, app: Any) -> None:
        """Shutdown handler: stop consumers, bridge, cancel dwell timers, close dispatcher.

        Shutdown order:
        1. Stop geofence and reload consumers (stop accepting new messages).
        2. Stop bridge (stop ingesting new MQTT events).
        3. Cancel all pending dwell timers.
        4. Close dispatcher (closes owned HTTP session).
        5. Stop producers.

        Args:
            app: The aiohttp application (passed by aiohttp signal dispatch).
        """
        logger.info("GeofencingExtension: shutting down")

        # 1. Stop consumers
        for consumer in [self._geo_consumer, self._reload_consumer]:
            if consumer is not None:
                try:
                    await consumer.stop(app)
                except Exception as exc:
                    logger.warning(
                        "GeofencingExtension: error stopping consumer %s: %s",
                        getattr(consumer, "_name_", consumer.__class__.__name__),
                        exc,
                    )

        # 2. Stop bridge
        if self._bridge is not None:
            try:
                await self._bridge.stop(app)
            except Exception as exc:
                logger.warning("GeofencingExtension: error stopping bridge: %s", exc)

        # 3. Cancel all pending dwell timers
        if self._engine is not None:
            timer_count = len(self._engine._dwell_timers)
            for timer in list(self._engine._dwell_timers.values()):
                timer.cancel()
            if timer_count:
                logger.debug(
                    "GeofencingExtension: cancelled %d dwell timers", timer_count
                )

        # 4. Close dispatcher (closes owned HTTP session)
        if self._dispatcher is not None:
            await self._dispatcher.aclose()

        # 5. Stop producers
        if self._downlink is not None:
            await self._downlink.stop(app)
        if self._reload_publisher is not None:
            await self._reload_publisher.stop(app)
        if self._internal_publisher is not None:
            await self._internal_publisher.stop(app)

        logger.info("GeofencingExtension: shutdown complete")

    # ------------------------------------------------------------------
    # DB loader helpers
    # ------------------------------------------------------------------

    async def _load_geofences(self) -> list[Geofence]:
        """Load all active geofences from the database.

        Called by :class:`GeofenceEngine` on startup and reload.

        Returns:
            List of :class:`Geofence` dataclass instances.
        """
        if self._app_db is None:
            logger.warning("_load_geofences: no DB configured; returning empty list")
            return []

        try:
            rows = await self._app_db.fetch_all(
                "SELECT id, tenant_id, name, polygon, active, dwell_seconds, "
                "created_at, updated_at FROM geofences WHERE active = TRUE"
            )
            result = []
            for row in (rows or []):
                result.append(
                    Geofence(
                        id=row["id"],
                        tenant_id=str(row["tenant_id"]),
                        name=row["name"],
                        polygon=row["polygon"],
                        active=bool(row["active"]),
                        dwell_seconds=row.get("dwell_seconds"),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            logger.debug("_load_geofences: loaded %d geofences", len(result))
            return result
        except Exception as exc:
            logger.error("_load_geofences: DB error: %s", exc)
            return []

    async def _load_webhooks(self, transition: GeofenceTransition) -> list[Webhook]:
        """Load matching active webhooks for a transition's tenant + geofence.

        Filters by:
        - ``tenant_id = transition.tenant_id``
        - ``active = TRUE``
        - ``geofence_filter IS NULL OR geofence_filter = transition.geofence_id``

        Args:
            transition: The geofence transition to filter webhooks for.

        Returns:
            List of matching :class:`Webhook` dataclass instances.
        """
        if self._app_db is None:
            return []

        try:
            rows = await self._app_db.fetch_all(
                "SELECT id, tenant_id, url, secret_encrypted, geofence_filter, "
                "active, created_at, updated_at FROM webhooks "
                "WHERE tenant_id = $1 AND active = TRUE "
                "AND (geofence_filter IS NULL OR geofence_filter = $2)",
                str(transition.tenant_id),
                transition.geofence_id,
            )
            result = []
            for row in (rows or []):
                result.append(
                    Webhook(
                        id=row["id"],
                        tenant_id=str(row["tenant_id"]),
                        url=row["url"],
                        secret_encrypted=bytes(row["secret_encrypted"]),
                        geofence_filter=row.get("geofence_filter"),
                        active=bool(row["active"]),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return result
        except Exception as exc:
            logger.error("_load_webhooks: DB error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Hot-reload handler
    # ------------------------------------------------------------------

    async def _on_reload_message(self, message: Any, body: Any) -> None:
        """Handle ``geofence.changed`` fanout messages for hot reload.

        Parses the geofence_id from the message body and calls
        :meth:`GeofenceEngine.reload_one`.

        Args:
            message: Raw aiormq delivered message.
            body: Pre-decoded body (str or dict).
        """
        try:
            if isinstance(body, str):
                event = json.loads(body)
            else:
                event = body
            geofence_id = event.get("geofence_id")
            if geofence_id is not None:
                await self._engine.reload_one(str(geofence_id))
                logger.debug(
                    "_on_reload_message: reloaded geofence_id=%s", geofence_id
                )
        except Exception as exc:
            logger.error("_on_reload_message: error processing reload event: %s", exc)
