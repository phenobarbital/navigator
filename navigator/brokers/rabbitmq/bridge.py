"""EmployeeEventsBridge — MQTT-Plugin Ingestion Bridge.

Consumes MQTT-originated AMQP messages from ``amq.topic`` / ``employees.#``,
performs ``eventId``-based deduplication via Redis, validates ``schemaVersion``
and envelope/JWT ``employeeId`` consistency, fans batched ``positions[]`` into
per-position AMQP messages, and republishes to the domain ``employee.events``
topic exchange.

Architecture note (from spec):
    The RabbitMQ MQTT plugin auto-translates MQTT topic ``employees/123/location``
    to AMQP routing key ``employees.123.location`` on ``amq.topic``.  This bridge
    binds to ``amq.topic`` / ``employees.#`` to receive all employee telemetry.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 3.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiormq

from navigator.brokers.rabbitmq.consumer import RMQConsumer
from navigator.conf import (
    EMPLOYEE_EVENTS_EXCHANGE,
    MQTT_ACCEPTED_SCHEMA_VERSIONS,
    MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY,
    MQTT_EVENT_DEDUP_REDIS_URL,
    MQTT_EVENT_DEDUP_TTL,
    MQTT_MAX_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

# Routing key constants
_TYPE_TO_ROUTING_KEY: dict[str, str] = {
    "status": "employee.status.updated",
    "events.check-in": "employee.checkin.recorded",
    "events/check-in": "employee.checkin.recorded",
    "events.incidents": "employee.incident.created",
    "events/incidents": "employee.incident.created",
}
_DLQ_EXCHANGE_PREFIX = "employee.events.dlq"


class EmployeeEventsBridge(RMQConsumer):
    """MQTT-Plugin ingestion bridge.

    Subscribes to ``amq.topic`` / ``employees.#``, deduplicates by ``eventId``
    (and per-position by ``{eventId}:{positionIndex}``), validates
    ``schemaVersion``, enforces envelope/JWT ``employeeId`` consistency, fans
    batched ``positions[]`` into individual AMQP messages on
    ``employee.events``, and routes non-batch events with correct routing keys.

    Args:
        dedup_ttl: Redis TTL for ``eventId`` dedup keys, in seconds.
        dedup_redis_url: Redis URL for dedup storage.  Defaults to
            ``MQTT_EVENT_DEDUP_REDIS_URL`` (which falls back to ``CACHE_URL``).
        accepted_schema_versions: Set of accepted ``schemaVersion`` integers.
        max_batch_size: Maximum allowed ``positions`` array length.
        enforce_employee_id: Whether to enforce ``envelope.employeeId ==
            message.user_id``.
        employee_events_exchange: Target AMQP exchange for republished messages.
        **kwargs: Passed through to :class:`RMQConsumer`.
    """

    _name_: str = "employee_events_bridge"

    def __init__(
        self,
        *,
        dedup_ttl: int = MQTT_EVENT_DEDUP_TTL,
        dedup_redis_url: str = MQTT_EVENT_DEDUP_REDIS_URL,
        accepted_schema_versions: set = None,
        max_batch_size: int = MQTT_MAX_BATCH_SIZE,
        enforce_employee_id: bool = MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY,
        employee_events_exchange: str = EMPLOYEE_EVENTS_EXCHANGE,
        **kwargs,
    ) -> None:
        """Initialize EmployeeEventsBridge.

        Args:
            dedup_ttl: Redis TTL (seconds) for event dedup keys.
            dedup_redis_url: Redis connection URL for dedup store.
            accepted_schema_versions: Set of valid ``schemaVersion`` ints.
            max_batch_size: Maximum accepted batch size.
            enforce_employee_id: Enforce MQTT username == envelope employeeId.
            employee_events_exchange: AMQP exchange for republished events.
            **kwargs: Forwarded to RMQConsumer.
        """
        super().__init__(**kwargs)
        self._dedup_ttl = dedup_ttl
        self._dedup_redis_url = dedup_redis_url
        self._accepted_schema_versions = (
            accepted_schema_versions
            if accepted_schema_versions is not None
            else MQTT_ACCEPTED_SCHEMA_VERSIONS
        )
        self._max_batch_size = max_batch_size
        self._enforce_employee_id = enforce_employee_id
        self._employee_events_exchange = employee_events_exchange
        self._redis: Optional[Any] = None  # built lazily in start()
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, app) -> None:
        """Connect to RabbitMQ, build Redis client, and start consuming.

        Overrides :meth:`RMQConsumer.start` to subscribe to
        ``amq.topic`` / ``employees.#`` using a fixed queue name.

        Args:
            app: The aiohttp web.Application instance.
        """
        # Build Redis client lazily here to keep module import cheap.
        if self._redis is None:
            try:
                from redis.asyncio import from_url as redis_from_url  # type: ignore[import]

                self._redis = redis_from_url(self._dedup_redis_url)
                self.logger.debug(
                    "Redis dedup client connected to %s", self._dedup_redis_url
                )
            except Exception as exc:
                self.logger.warning(
                    "Could not connect Redis dedup client: %s — failing open", exc
                )
                self._redis = None

        # Connect AMQP and ensure the downstream exchange exists.
        await self.ensure_connection()
        await self.ensure_exchange(
            self._employee_events_exchange, exchange_type="topic"
        )

        # Subscribe to MQTT-originated messages.
        await self.subscribe_to_events(
            exchange="amq.topic",
            queue_name="employee.events.ingest",
            routing_key="employees.#",
            callback=self._handle_envelope,
            exchange_type="topic",
        )
        self.logger.info(
            "EmployeeEventsBridge started — subscribed to amq.topic / employees.#"
        )

    # ------------------------------------------------------------------
    # Dedup helpers
    # ------------------------------------------------------------------

    async def _dedup_set(self, key: str) -> bool:
        """Attempt to SET NX a dedup key.  Returns True if key was NEW (not a dup).

        On Redis error, logs WARNING and returns True (fail-open).

        Args:
            key: Redis key string.

        Returns:
            True if the key was new (proceed with republish).
            False if the key already existed (skip duplicate).
        """
        if self._redis is None:
            return True  # fail-open
        try:
            result = await self._redis.set(
                name=key, value="1", ex=self._dedup_ttl, nx=True
            )
            return result is not None  # None means key already existed
        except Exception as exc:
            self.logger.warning(
                "Redis dedup error for key %s: %s — failing open", key, exc
            )
            return True  # fail-open

    # ------------------------------------------------------------------
    # DLQ helper
    # ------------------------------------------------------------------

    async def _to_dlq(self, body: Any, reason: str, kind: str) -> None:
        """Publish a rejected message to the appropriate DLQ exchange.

        Args:
            body: The original message body (dict or str).
            reason: Human-readable rejection reason.
            kind: DLQ suffix (e.g. ``"schema"``, ``"envelope"``).
        """
        dlq_exchange = f"{_DLQ_EXCHANGE_PREFIX}.{kind}"
        try:
            await self.ensure_exchange(dlq_exchange, exchange_type="direct")
            await self.publish_message(
                body=body if isinstance(body, dict) else {"raw": str(body)},
                queue_name=dlq_exchange,
                routing_key="",
                headers={"rejection_reason": reason},
            )
        except Exception as exc:
            self.logger.error(
                "Failed to publish to DLQ %s: %s", dlq_exchange, exc
            )

    # ------------------------------------------------------------------
    # Message handler
    # ------------------------------------------------------------------

    async def _handle_envelope(
        self,
        message: aiormq.abc.DeliveredMessage,
        body: Any,
    ) -> None:
        """Process a single MQTT-originated AMQP message.

        Called by :meth:`RabbitMQConnection.wrap_callback` after JSON decoding.

        Args:
            message: Raw aiormq delivered message (provides properties).
            body: JSON-decoded body (dict, or str on decode failure).
        """
        # ----- Guard: ensure body is a dict ----------------------------
        if not isinstance(body, dict):
            try:
                body = json.loads(body) if isinstance(body, str) else {}
            except (json.JSONDecodeError, TypeError):
                self.logger.warning("Bridge: non-JSON body received, sending to DLQ")
                await self._to_dlq(body, "non-json body", "envelope")
                return

        # ----- Extract envelope fields ---------------------------------
        event_id: Optional[str] = body.get("eventId")
        employee_id: Optional[str] = str(body.get("employeeId", ""))
        msg_type: Optional[str] = body.get("type")
        schema_version = body.get("schemaVersion")
        positions = body.get("positions", [])
        payload = body.get("payload")
        timestamp = body.get("timestamp")

        if not event_id or not employee_id or not msg_type or schema_version is None:
            self.logger.warning(
                "Bridge: missing required envelope fields (eventId/employeeId/type/schemaVersion)"
            )
            await self._to_dlq(body, "missing required fields", "envelope")
            return

        # ----- Schema version check ------------------------------------
        try:
            schema_version_int = int(schema_version)
        except (TypeError, ValueError):
            schema_version_int = -1

        if schema_version_int not in self._accepted_schema_versions:
            self.logger.warning(
                "Bridge: rejected schemaVersion=%s for eventId=%s",
                schema_version,
                event_id,
            )
            await self._to_dlq(
                body,
                f"unsupported schemaVersion={schema_version}",
                "schema",
            )
            return

        # ----- employeeId enforcement ----------------------------------
        if self._enforce_employee_id:
            props = message.header.properties or aiormq.spec.Basic.Properties()
            mqtt_username: Optional[str] = getattr(props, "user_id", None)
            if mqtt_username is not None and str(mqtt_username) != str(employee_id):
                self.logger.warning(
                    "Bridge: employeeId mismatch — mqtt_username=%s "
                    "envelope_employee_id=%s eventId=%s",
                    mqtt_username,
                    employee_id,
                    event_id,
                )
                await self._to_dlq(
                    body,
                    f"employeeId mismatch: mqtt={mqtt_username} envelope={employee_id}",
                    "employee_id_mismatch",
                )
                return

        # ----- Event-level dedup ---------------------------------------
        dedup_key = f"mqtt:dedup:{event_id}"
        is_new = await self._dedup_set(dedup_key)
        # For location.batch we do per-position dedup later; for non-batch
        # types, skip entire message if event-level key was already set.
        if not is_new and msg_type != "location.batch":
            self.logger.debug("Bridge: duplicate eventId=%s — skipping", event_id)
            return

        # ----- Routing -------------------------------------------------
        if msg_type == "location.batch":
            await self._handle_location_batch(body, event_id, employee_id, positions)
        else:
            routing_key = _TYPE_TO_ROUTING_KEY.get(msg_type)
            if routing_key is None:
                self.logger.warning(
                    "Bridge: unknown type=%s for eventId=%s — DLQ", msg_type, event_id
                )
                await self._to_dlq(body, f"unknown type={msg_type}", "unknown_type")
                return
            await self.publish_message(
                body={
                    "employeeId": employee_id,
                    "type": msg_type,
                    "payload": payload,
                    "timestamp": timestamp,
                },
                queue_name=self._employee_events_exchange,
                routing_key=routing_key,
                headers={"eventId": event_id},
            )
            self.logger.debug(
                "Bridge: republished type=%s eventId=%s key=%s",
                msg_type,
                event_id,
                routing_key,
            )

    async def _handle_location_batch(
        self,
        body: dict,
        event_id: str,
        employee_id: str,
        positions: Any,
    ) -> None:
        """Fan out a ``location.batch`` envelope into per-position AMQP messages.

        Args:
            body: Original envelope dict (for DLQ reference).
            event_id: The batch ``eventId``.
            employee_id: The ``employeeId`` from the envelope.
            positions: The ``positions`` list from the envelope.
        """
        if not isinstance(positions, list) or len(positions) == 0:
            self.logger.warning(
                "Bridge: empty positions[] for eventId=%s — DLQ", event_id
            )
            await self._to_dlq(body, "empty positions array", "empty_batch")
            return

        if len(positions) > self._max_batch_size:
            self.logger.warning(
                "Bridge: positions[] size %d > max %d for eventId=%s — DLQ",
                len(positions),
                self._max_batch_size,
                event_id,
            )
            await self._to_dlq(
                body,
                f"batch too large: {len(positions)} > {self._max_batch_size}",
                "batch_size",
            )
            return

        batch_size = len(positions)
        for idx, position in enumerate(positions):
            per_pos_key = f"mqtt:dedup:{event_id}:{idx}"
            is_new = await self._dedup_set(per_pos_key)
            if not is_new:
                self.logger.debug(
                    "Bridge: duplicate position eventId=%s idx=%d — skipping",
                    event_id,
                    idx,
                )
                continue

            pos_body = {
                "employeeId": employee_id,
                "lat": position.get("lat"),
                "lng": position.get("lng"),
                "ts": position.get("ts"),
            }
            tenant_id = body.get("tenantId")
            if tenant_id:
                pos_body["tenantId"] = tenant_id

            await self.publish_message(
                body=pos_body,
                queue_name=self._employee_events_exchange,
                routing_key="employee.location.updated",
                headers={
                    "eventId": event_id,
                    "positionIndex": idx,
                    "batchSize": batch_size,
                    **({"tenantId": tenant_id} if tenant_id else {}),
                },
            )
            self.logger.debug(
                "Bridge: published position %d/%d for eventId=%s",
                idx + 1,
                batch_size,
                event_id,
            )
