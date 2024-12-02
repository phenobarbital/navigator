"""
RabbitMQ Consumer.

can be used to consume messages from RabbitMQ.
"""
from typing import Union, Optional, Any
from collections.abc import Callable, Awaitable
import asyncio
from aiohttp import web
from navconfig.logging import logging
from .connection import SQSConnection
from ..consumer import BrokerConsumer


class SQSConsumer(SQSConnection, BrokerConsumer):
    """
    SQSConsumer.

    Broker Client (Consumer) using Amazon AWS SQS.
    """
    _name_: str = "sqs_consumer"

    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        callback: Optional[Union[Awaitable, Callable]] = None,
        **kwargs
    ):
        self._queue_name = kwargs.get('queue_name', 'navigator')
        super().__init__(
            credentials=credentials,
            timeout=timeout,
            callback=callback,
            **kwargs
        )
        self.logger = logging.getLogger('SQSConsumer')

    async def subscriber_callback(
        self,
        message: Any,
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
        queue_name: str,
        callback: Union[Callable, Awaitable],
        max_messages: int = 10,
        wait_time: int = 10,
        idle_sleep: int = 5,
        **kwargs
    ) -> None:
        """
        Subscribe to events from a specific Queue.
        """
        # Declare the queue
        await self.ensure_connection()
        try:
            self.logger.notice(
                f"Starting SQS consumer for queue: {queue_name}"
            )
            self.consumer_task = asyncio.create_task(
                self.consume_messages(
                    queue_name=queue_name,
                    callback=callback,
                    max_messages=max_messages,
                    wait_time=wait_time,
                    idle_sleep=idle_sleep,
                    **kwargs
                )
            )
        except Exception as e:
            self.logger.error(
                f"Error subscribing to events: {e}"
            )
            raise

    async def start(self, app: web.Application) -> None:
        """Signal Function to be called when the application is started.

        Connect to RabbitMQ, and start consuming.
        """
        await super().start(app)
        await self.subscribe_to_events(
            queue_name=self._queue_name,
            callback=self._callback_
        )

    async def stop(self, app: web.Application) -> None:
        """Signal Function to be called when the application is stopped.

        Stop consuming and disconnect from SQS.
        """
        await self.stop_consumer()
        await super().stop(app)

    async def stop_consumer(self):
        """
        Stop the SQS consumer task gracefully.
        """
        if self.consumer_task:
            self.logger.info("Stopping SQS consumer...")
            self.consumer_task.cancel()  # Cancel the task
            try:
                await self.consumer_task  # Await task cancellation
            except asyncio.CancelledError:
                self.logger.info("SQS consumer task cancelled.")
            self.consumer_task = None
