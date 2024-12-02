"""
RabbitMQ Consumer.

can be used to consume messages from RabbitMQ.
"""
from typing import Union, Optional
from collections.abc import Callable, Awaitable
from aiohttp import web
import aiormq
from navconfig.logging import logging
from .connection import RabbitMQConnection
from ..consumer import BrokerConsumer


# Disable Debug Logging for AIORMQ
logging.getLogger('aiormq').setLevel(logging.INFO)


class RMQConsumer(RabbitMQConnection, BrokerConsumer):
    """
    RMQConsumer.

    Broker Client (Consumer) using RabbitMQ.
    """
    _name_: str = "rabbitmq_consumer"

    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        callback: Optional[Union[Awaitable, Callable]] = None,
        **kwargs
    ):
        self._routing_key = kwargs.get('routing_key', '*')
        self._exchange_type = kwargs.get('exchange_type', 'topic')
        self._exchange_name = kwargs.get('exchange_name', 'navigator')
        self._queue_name = kwargs.get('queue_name', None)
        if self._queue_name:
            self._exchange_name = self._queue_name
        super().__init__(
            credentials=credentials,
            timeout=timeout,
            callback=callback,
            **kwargs
        )
        self.logger = logging.getLogger('RMQConsumer')

    async def subscriber_callback(
        self,
        message: aiormq.abc.DeliveredMessage,
        body: str
    ) -> None:
        """
        Default Callback for Event Subscription.
        """
        try:
            print(f"Received message: {message}")
            print(f"Received Body: {body}")
            self.logger.info(f'Received Message: {body}')
        except Exception as e:
            self.logger.error(
                f"Error in subscriber_callback: {e}"
            )
            raise

    async def event_subscribe(
        self,
        queue_name: str,
        callback: Union[Callable, Awaitable]
    ) -> None:
        """Event Subscribe.
        """
        await self.consume_messages(
            queue_name=queue_name,
            callback=self.wrap_callback(callback)
        )

    async def subscribe_to_events(
        self,
        exchange: str,
        queue_name: str,
        routing_key: str,
        callback: Union[Callable, Awaitable],
        exchange_type: str = 'topic',
        durable: bool = True,
        prefetch_count: int = 1,
        requeue_on_fail: bool = True,
        max_retries: int = 3,
        **kwargs
    ) -> None:
        """
        Subscribe to events from a specific exchange with a given routing key.
        """
        # Declare the queue
        await self.ensure_connection()
        try:
            await self.ensure_exchange(exchange_name=exchange, exchange_type=exchange_type)
            await self._channel.queue_declare(queue=queue_name, durable=durable)

            # Bind the queue to the exchange
            await self._channel.queue_bind(
                queue=queue_name,
                exchange=exchange,
                routing_key=routing_key
            )

            # Set QoS (Quality of Service) settings
            await self._channel.basic_qos(prefetch_count=prefetch_count)

            # Start consuming messages from the queue
            await self._channel.basic_consume(
                queue=queue_name,
                consumer_callback=self.wrap_callback(
                    callback,
                    requeue_on_fail=requeue_on_fail,
                    max_retries=max_retries
                ),
                **kwargs
            )
            self.logger.info(
                f"Subscribed to queue '{queue_name}' on exchange '{exchange}' with routing '{routing_key}'."
            )
        except Exception as e:
            self.logger.error(f"Error subscribing to events: {e}")
            raise

    async def start(self, app: web.Application) -> None:
        """Signal Function to be called when the application is started.

        Connect to RabbitMQ, and start consuming.
        """
        await super().start(app)
        await self.subscribe_to_events(
            exchange=self._exchange_name,
            queue_name=self._queue_name,
            routing_key=self._routing_key,
            callback=self._callback_,
            exchange_type=self._exchange_type,
            durable=True,
            prefetch_count=1,
            requeue_on_fail=True,
        )
