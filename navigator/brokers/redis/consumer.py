"""
Redis Consumer.

Can be used to consume messages from Redis Streams.
"""
from typing import Union, Optional, Any
from collections.abc import Callable, Awaitable
import asyncio
from aiohttp import web
from navconfig.logging import logging
from .connection import RedisConnection
from ..consumer import BrokerConsumer


class RedisConsumer(RedisConnection, BrokerConsumer):
    """
    RedisConsumer.

    Broker Client (Consumer) using Redis Streams.
    """
    _name_: str = "redis_consumer"

    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        callback: Optional[Union[Awaitable, Callable]] = None,
        **kwargs
    ):
        self._queue_name = kwargs.get('queue_name', 'message_stream')
        self._group_name = kwargs.get('group_name', 'default_group')
        self._consumer_name = kwargs.get('consumer_name', 'default_consumer')
        super().__init__(
            credentials=credentials,
            timeout=timeout,
            callback=callback,
            queue_name=self._queue_name,
            group_name=self._group_name,
            consumer_name=self._consumer_name,
            **kwargs
        )
        self.logger = logging.getLogger('RedisConsumer')
        self.consumer_task: Optional[asyncio.Task] = None
        self._callback_ = callback if callback else self.subscriber_callback

    async def subscriber_callback(
        self,
        message_id: str,
        body: Any
    ) -> None:
        """
        Default Callback for Event Subscription.
        """
        try:
            print(f"Received message ID: {message_id}")
            print(f"Received Body: {body}")
            self.logger.info(f'Received Message ID: {message_id} Body: {body}')
        except Exception as e:
            self.logger.error(f"Error in subscriber_callback: {e}")
            raise

    def wrap_callback(
        self,
        callback: Callable[[Any, Any], Awaitable[None]],
    ) -> Callable[[Any, Any], Awaitable[None]]:
        """
        Wraps the user-provided callback for message handling.
        """
        async def wrapped_callback(message_id, body):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message_id, body)
                else:
                    callback(message_id, body)
            except Exception as e:
                self.logger.error(f"Error processing message {message_id}: {e}")
        return wrapped_callback

    async def event_subscribe(
        self,
        queue_name: Optional[str],
        callback: Union[Callable, Awaitable],
        **kwargs
    ) -> None:
        """Event Subscribe."""
        await self.consume_messages(
            queue_name=queue_name,
            callback=self.wrap_callback(callback),
            **kwargs
        )

    async def subscribe_to_events(
        self,
        queue_name: Optional[str],
        callback: Union[Callable, Awaitable],
        **kwargs
    ) -> None:
        """
        Subscribe to events from a specific Stream.
        """
        # Declare the stream and ensure group exists
        await self.ensure_connection()
        try:
            self.logger.info(f"Starting Redis consumer for stream: {queue_name}")
            self.consumer_task = asyncio.create_task(
                self.consume_messages(
                    queue_name=queue_name,
                    callback=callback,
                    **kwargs
                )
            )
        except Exception as e:
            self.logger.error(f"Error subscribing to events: {e}")
            raise

    async def stop_consumer(self):
        """
        Stop the Redis consumer task gracefully.
        """
        if self.consumer_task:
            self.logger.info("Stopping Redis consumer...")
            self.consumer_task.cancel()  # Cancel the task
            try:
                await self.consumer_task  # Await task cancellation
            except asyncio.CancelledError:
                self.logger.info("Redis consumer task cancelled.")
            self.consumer_task = None

    async def start(self, app: web.Application) -> None:
        """Signal Function to be called when the application is started.

        Connect to Redis, and start consuming.
        """
        await super().start(app)
        await self.subscribe_to_events(
            queue_name=self._queue_name,
            callback=self._callback_
        )

    async def stop(self, app: web.Application) -> None:
        """Signal Function to be called when the application is stopped.

        Stop consuming and disconnect from Redis.
        """
        await self.stop_consumer()
        await super().stop(app)
