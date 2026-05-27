"""NotificationDispatcher — Multi-Channel Fan-Out.

Fans out each :class:`~navigator.ext.geofencing.models.GeofenceTransition`
to five concurrent notification channels:

1. **MQTT downlink** — back-channel push to the employee's device.
2. **FCM push** — Firebase Cloud Messaging (iOS via APNs bridge, Android).
3. **Internal RabbitMQ fanout** — ``geofence.notifications`` fanout exchange
   so downstream consumers can subscribe without modifying this code.
4. **Webhooks** — signed HTTP callbacks to third-party integrations.
5. **Python handlers** — in-process coroutines registered via
   :func:`~navigator.ext.geofencing.decorators.on_geofence_event`.

All channels run inside a single ``asyncio.gather(..., return_exceptions=True)``
so a slow or failing channel never blocks the others.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 7.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Optional

import aiohttp

from navigator.conf import GEOFENCE_HANDLER_TIMEOUT
from navigator.brokers.rabbitmq import MQTTDownlinkPublisher, RMQProducer
from navigator.ext.geofencing.models import GeofenceTransition, Webhook
from navigator.ext.geofencing.decorators import get_matching_handlers
from navigator.ext.geofencing.webhooks import dispatch_webhook
from navigator.ext.geofencing.push_providers import PushProvider

logger = logging.getLogger(__name__)


def _build_payload(transition: GeofenceTransition) -> dict:
    """Build the canonical notification payload from a transition.

    Args:
        transition: The :class:`GeofenceTransition` to serialise.

    Returns:
        JSON-serialisable dict with all transition fields.
    """
    return {
        "kind": transition.kind,
        "geofence_id": transition.geofence_id,
        "tenant_id": transition.tenant_id,
        "employee_id": transition.employee_id,
        "ts": transition.ts.isoformat() if hasattr(transition.ts, "isoformat") else str(transition.ts),
        "location": {
            "lat": transition.location.lat,
            "lng": transition.location.lng,
            "ts": transition.location.ts.isoformat() if hasattr(transition.location.ts, "isoformat") else str(transition.location.ts),
        },
        "source_event_id": str(transition.source_event_id),
        "dwell_duration": transition.dwell_duration,
    }


class NotificationDispatcher:
    """Fan-out dispatcher for geofence transition notifications.

    Concurrently dispatches each :class:`GeofenceTransition` to up to five
    notification channels.  Per-channel exceptions are logged and dropped —
    they never propagate to the caller.

    Args:
        downlink: :class:`MQTTDownlinkPublisher` for back-channel MQTT push
            to employee devices.
        internal_publisher: :class:`RMQProducer` for the internal
            ``geofence.notifications`` fanout exchange.
        fcm: Optional :class:`~navigator.ext.geofencing.push_providers.PushProvider`
            for FCM push notifications.  When ``None``, the FCM channel is
            skipped silently.
        webhook_loader: Async callable that receives the transition and returns
            a list of matching :class:`Webhook` rows (filtered by tenant and
            optional geofence filter).
        webhook_decrypt: Callable that decrypts ``webhook.secret_encrypted``
            and returns the raw HMAC secret bytes.
        device_token_lookup: Async callable mapping ``employee_id`` to a list
            of FCM device registration tokens.
        geofence_name_resolver: Optional callable mapping ``geofence_id``
            (``int``) to a human-readable name string.  Used for
            ``geofence_name`` filter matching in the handler registry.
        handler_timeout: Seconds before a Python handler coroutine is
            cancelled (default: :data:`~navigator.conf.GEOFENCE_HANDLER_TIMEOUT`).
        http_session: Optional ``aiohttp.ClientSession`` for webhook HTTP
            calls.  If ``None``, an internal session is created and owned by
            this dispatcher (closed in :meth:`aclose`).

    Example::

        dispatcher = NotificationDispatcher(
            downlink=downlink_publisher,
            internal_publisher=rmq_producer,
            fcm=fcm_provider,
            webhook_loader=load_webhooks_for_transition,
            webhook_decrypt=decrypt_fn,
            device_token_lookup=fetch_device_tokens,
        )
        await dispatcher.dispatch(transition)
    """

    def __init__(
        self,
        *,
        downlink: MQTTDownlinkPublisher,
        internal_publisher: RMQProducer,
        fcm: Optional[PushProvider],
        webhook_loader: Callable[[GeofenceTransition], Awaitable[list[Webhook]]],
        webhook_decrypt: Callable[[bytes], bytes],
        device_token_lookup: Callable[[str], Awaitable[list[str]]],
        geofence_name_resolver: Optional[Callable[[int], Optional[str]]] = None,
        handler_timeout: float = GEOFENCE_HANDLER_TIMEOUT,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialise the dispatcher.

        Args:
            downlink: MQTT downlink publisher.
            internal_publisher: RabbitMQ producer for the fanout exchange.
            fcm: Optional FCM push provider.
            webhook_loader: Async callable returning matching Webhook rows.
            webhook_decrypt: Callable to decrypt webhook HMAC secrets.
            device_token_lookup: Async callable resolving employee FCM tokens.
            geofence_name_resolver: Optional resolver for geofence names.
            handler_timeout: Timeout in seconds for each Python handler.
            http_session: Optional shared aiohttp session for webhooks.
        """
        self._downlink = downlink
        self._internal_publisher = internal_publisher
        self._fcm = fcm
        self._webhook_loader = webhook_loader
        self._decrypt = webhook_decrypt
        self._device_token_lookup = device_token_lookup
        self._geofence_name_resolver = geofence_name_resolver
        self._handler_timeout = handler_timeout

        if http_session is not None:
            self._session = http_session
            self._owns_session = False
        else:
            self._session = aiohttp.ClientSession()
            self._owns_session = True

        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(self, transition: GeofenceTransition) -> None:
        """Fan out a geofence transition to all five notification channels.

        All channels run concurrently via
        ``asyncio.gather(..., return_exceptions=True)``.  Per-channel
        exceptions are logged at WARNING/ERROR level and dropped — they
        never propagate to the caller.

        Args:
            transition: The geofence transition event to dispatch.
        """
        payload = _build_payload(transition)

        channel_coros = [
            self._channel_mqtt(transition, payload),
            self._channel_fcm(transition, payload),
            self._channel_internal(payload),
            self._channel_webhooks(transition, payload),
            self._channel_python_handlers(transition),
        ]

        results = await asyncio.gather(*channel_coros, return_exceptions=True)

        channel_names = ["mqtt", "fcm", "internal_rmq", "webhooks", "python_handlers"]
        for name, result in zip(channel_names, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "dispatch: channel=%s raised exception for transition "
                    "employee_id=%s geofence_id=%s kind=%s: %s",
                    name,
                    transition.employee_id,
                    transition.geofence_id,
                    transition.kind,
                    result,
                )

    async def aclose(self) -> None:
        """Close the internal aiohttp session if owned by this dispatcher.

        Should be called during application shutdown.
        """
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Channel implementations
    # ------------------------------------------------------------------

    async def _channel_mqtt(
        self, transition: GeofenceTransition, payload: dict
    ) -> None:
        """Channel 1: MQTT downlink to employee device.

        Args:
            transition: The geofence transition.
            payload: The canonical notification payload.
        """
        await self._downlink.publish_to_employee(
            transition.employee_id, "notifications", payload
        )
        self.logger.debug(
            "_channel_mqtt: dispatched employee_id=%s kind=%s",
            transition.employee_id,
            transition.kind,
        )

    async def _channel_fcm(
        self, transition: GeofenceTransition, payload: dict
    ) -> None:
        """Channel 2: FCM push notification to all registered device tokens.

        Skipped silently when :attr:`_fcm` is ``None``.

        Args:
            transition: The geofence transition.
            payload: The canonical notification payload.
        """
        if self._fcm is None:
            return

        tokens: list[str] = await self._device_token_lookup(transition.employee_id)
        if not tokens:
            self.logger.debug(
                "_channel_fcm: no device tokens for employee_id=%s",
                transition.employee_id,
            )
            return

        send_coros = [self._fcm.send(token, payload) for token in tokens]
        results = await asyncio.gather(*send_coros, return_exceptions=True)
        for token, result in zip(tokens, results):
            if isinstance(result, Exception):
                self.logger.warning(
                    "_channel_fcm: send failed employee_id=%s token=%s...: %s",
                    transition.employee_id,
                    token[:8],
                    result,
                )

    async def _channel_internal(self, payload: dict) -> None:
        """Channel 3: Internal RabbitMQ fanout exchange.

        Publishes to the ``geofence.notifications`` fanout exchange.  Fanout
        exchanges ignore the routing key — empty string is conventional.

        Args:
            payload: The canonical notification payload.
        """
        await self._internal_publisher.queue_event(
            payload,
            queue_name="geofence.notifications",
            routing_key="",
        )
        self.logger.debug("_channel_internal: published to geofence.notifications")

    async def _channel_webhooks(
        self, transition: GeofenceTransition, payload: dict
    ) -> None:
        """Channel 4: Signed HTTP webhooks to third-party integrations.

        Loads matching webhooks via the injected ``webhook_loader`` and
        dispatches each concurrently.

        Args:
            transition: The geofence transition (used by webhook_loader for
                tenant + geofence filtering).
            payload: The canonical notification payload to POST.
        """
        webhooks: list[Webhook] = await self._webhook_loader(transition)
        if not webhooks:
            return

        dispatch_coros = [
            dispatch_webhook(
                w,
                payload,
                session=self._session,
                decrypt=self._decrypt,
            )
            for w in webhooks
        ]
        results = await asyncio.gather(*dispatch_coros, return_exceptions=True)
        for webhook, result in zip(webhooks, results):
            if isinstance(result, Exception):
                self.logger.warning(
                    "_channel_webhooks: failed for url=%s: %s",
                    webhook.url,
                    result,
                )

    async def _channel_python_handlers(
        self, transition: GeofenceTransition
    ) -> None:
        """Channel 5: In-process Python handler coroutines.

        Retrieves matching handlers from the registry (via
        :func:`~navigator.ext.geofencing.decorators.get_matching_handlers`)
        and runs each concurrently with a per-handler timeout.  A handler
        that times out is cancelled; other handlers are unaffected.

        Args:
            transition: The geofence transition passed to each handler.
        """
        handlers = get_matching_handlers(
            transition,
            geofence_name_resolver=self._geofence_name_resolver,
        )
        if not handlers:
            return

        async def _run_with_timeout(handler: Callable) -> None:
            await asyncio.wait_for(
                handler(transition), timeout=self._handler_timeout
            )

        handler_coros = [_run_with_timeout(h) for h in handlers]
        results = await asyncio.gather(*handler_coros, return_exceptions=True)
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                handler_name = getattr(handler, "__name__", repr(handler))
                if isinstance(result, asyncio.TimeoutError):
                    self.logger.warning(
                        "_channel_python_handlers: handler=%s timed out "
                        "after %.1fs for employee_id=%s kind=%s",
                        handler_name,
                        self._handler_timeout,
                        transition.employee_id,
                        transition.kind,
                    )
                else:
                    self.logger.error(
                        "_channel_python_handlers: handler=%s raised for "
                        "employee_id=%s kind=%s: %s",
                        handler_name,
                        transition.employee_id,
                        transition.kind,
                        result,
                    )
