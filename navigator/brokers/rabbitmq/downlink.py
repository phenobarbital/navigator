"""MQTTDownlinkPublisher — AMQP-to-MQTT-Plugin Downlink.

Thin :class:`RMQProducer` subclass that routes AMQP messages onto
``amq.topic`` with routing key ``employees.{employee_id}.{topic}``.

The RabbitMQ MQTT plugin auto-delivers AMQP messages published on
``amq.topic / employees.123.notifications`` to MQTT subscribers of
``employees/123/notifications``.  This is the mechanism that pushes
geofence notifications back to mobile devices without needing a dedicated
MQTT client in Navigator (Option A).

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 4.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from navigator.brokers.rabbitmq.producer import RMQProducer

logger = logging.getLogger(__name__)


class MQTTDownlinkPublisher(RMQProducer):
    """Thin AMQP producer for MQTT downlink to mobile devices.

    Inherits all connection, retry, and serialization logic from
    :class:`RMQProducer` / :class:`RabbitMQConnection`.  The only addition
    is :meth:`publish_to_employee`, which constructs the correct routing key
    and enqueues the publish via the parent's worker-queue pattern.

    Args:
        credentials: RabbitMQ DSN.  Defaults to ``rabbitmq_dsn`` from conf.
        queue_size: Asyncio queue depth for the producer worker.
        num_workers: Number of background workers draining the queue.
        timeout: AMQP connection timeout in seconds.
        **kwargs: Forwarded to :class:`RMQProducer`.

    Example::

        publisher = MQTTDownlinkPublisher(credentials=rabbitmq_dsn)
        publisher.setup(app)

        # Later, inside an async context:
        await publisher.publish_to_employee(
            employee_id="123",
            topic="notifications",
            payload={"kind": "enter", "geofence_id": 42},
        )
    """

    _name_: str = "mqtt_downlink_publisher"

    def __init__(
        self,
        credentials: Union[str, dict] = None,
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs,
    ) -> None:
        """Initialize MQTTDownlinkPublisher.

        Args:
            credentials: RabbitMQ DSN.
            queue_size: Asyncio queue size for producer workers.
            num_workers: Number of worker tasks draining the queue.
            timeout: Connection timeout in seconds.
            **kwargs: Forwarded to RMQProducer.
        """
        super().__init__(
            credentials=credentials,
            queue_size=queue_size,
            num_workers=num_workers,
            timeout=timeout,
            **kwargs,
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    async def publish_to_employee(
        self,
        employee_id: str,
        topic: str,
        payload: dict,
    ) -> None:
        """Enqueue an AMQP message destined for an employee's MQTT subscription.

        The routing key ``employees.{employee_id}.{topic}`` causes RabbitMQ's
        MQTT plugin to deliver the message to any MQTT client subscribed to
        ``employees/{employee_id}/{topic}``.

        Args:
            employee_id: Target employee identifier (maps to the MQTT client
                username / MQTT topic namespace segment).
            topic: Topic suffix (e.g. ``"notifications"``, ``"commands"``).
            payload: JSON-serializable dict that becomes the AMQP message body.

        Note:
            ``amq.topic`` is RabbitMQ's built-in topic exchange.  Do **not**
            redeclare it with a different type — the call to
            ``ensure_exchange("amq.topic", exchange_type="topic")`` within
            ``publish_message`` is idempotent for the built-in exchange.
        """
        routing_key = f"employees.{employee_id}.{topic}"
        await self.queue_event(
            body=payload,
            queue_name="amq.topic",
            routing_key=routing_key,
        )
        self.logger.debug(
            "MQTTDownlinkPublisher: enqueued message for employee=%s topic=%s",
            employee_id,
            topic,
        )
