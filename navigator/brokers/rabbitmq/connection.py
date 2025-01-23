"""
RabbitMQ interface (connection and disconnections).
"""
from typing import Optional, Union, Any
from collections.abc import Callable, Awaitable
import asyncio
from dataclasses import is_dataclass
import aiormq
from aiormq.abc import AbstractConnection, AbstractChannel
from datamodel import BaseModel
from datamodel.parsers.json import json_encoder, json_decoder
from navigator.exceptions import ValidationError
from ...conf import rabbitmq_dsn
from ..wrapper import BaseWrapper
from ..connection import BaseConnection

class RabbitMQConnection(BaseConnection):
    """
    Manages connection and disconnection of RabbitMQ Service.
    """
    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        self._dsn = credentials if credentials is not None else rabbitmq_dsn
        print('DSN > ', rabbitmq_dsn)
        super().__init__(credentials=credentials, timeout=timeout, **kwargs)
        self._connection: Optional[AbstractConnection] = None
        self._channel: Optional[AbstractChannel] = None

    def get_channel(self) -> Optional[AbstractChannel]:
        return self._channel

    async def connect(self) -> None:
        """
        Creates a Connection to RabbitMQ Server.
        """
        try:
            self.logger.debug(
                f":: Connecting to RabbitMQ: {self._dsn}"
            )
            async with self._lock:
                self._connection = await asyncio.wait_for(
                    aiormq.connect(
                        self._dsn
                    ),
                    timeout=self._timeout
                )
                self.reconnect_attempts = 0
                self._channel = await self._connection.channel()
                if not self._monitor_task or self._monitor_task.done():
                    await self._start_connection_monitor()
        except asyncio.TimeoutError:
            self.logger.error("Connection timed out")
            await self.schedule_reconnect()
        except Exception as err:
            self.logger.error(
                f"Error while connecting to RabbitMQ: {err}"
            )
            await self.schedule_reconnect()

    async def _start_connection_monitor(self):
        """Start a background task to monitor the RabbitMQ connection."""
        self._monitor_task = asyncio.create_task(
            self.connection_monitor()
        )

    async def connection_monitor(self):
        """Monitor the RabbitMQ connection and
            attempt to reconnect if disconnected.
        """
        while True:
            if not self._connection or self._connection.is_closed:
                self.logger.warning(
                    "Connection lost. Attempting to reconnect..."
                )
                try:
                    await self.connect()
                except Exception as e:
                    self.logger.error(f"Reconnection attempt failed: {e}")
            await asyncio.sleep(60)

    async def schedule_reconnect(self):
        """
        Using exponential Backoff to schedule reconnections (in seconds).
        """
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = self.reconnect_delay * (
                2 ** (self.reconnect_attempts - 1)
            )  # Exponential backoff
            self.logger.info(
                f"Scheduling reconnect in {delay} seconds..."
            )
            await asyncio.sleep(delay)
            await self.connect()
        else:
            self.logger.error(
                "RabbitMQ: Max reconnect attempts reached. Giving up."
            )
            raise RuntimeError(
                "Unable to connect to RabbitMQ Server."
            )

    async def disconnect(self) -> None:
        """
        Disconnect from RabbitMQ.
        """
        if self._channel is not None:
            try:
                await self._channel.close()
                self._channel = None
            except Exception as err:
                self.logger.warning(
                    f"Error while closing channel: {err}"
                )
        if self._connection is not None:
            try:
                await self._connection.close()
                self._connection = None
            except Exception as err:
                self.logger.warning(
                    f"Error while closing connection: {err}"
                )
        # finishing the Monitoring Task.
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def ensure_connection(self) -> None:
        """
        Ensures that the connection is active.
        """
        if self._connection is None or self._connection.is_closed:
            await self.connect()

    async def create_exchange(
        self,
        exchange_name: str,
        exchange_type: str = 'topic',
        durable: bool = True,
        **kwargs
    ):
        """
        Declare an exchange on RabbitMQ.

        Methods to create and ensure the existence of exchanges.
        """
        if not self._channel:
            self.logger.error(
                "RabbitMQ channel is not established."
            )
            return

        try:
            await self._channel.exchange_declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                durable=durable,
                arguments=kwargs
            )
            self.logger.info(
                f"Exchange '{exchange_name}' declared successfully."
            )
        except Exception as e:
            self.logger.error(
                f"Failed to declare exchange '{exchange_name}': {e}"
            )

    async def ensure_exchange(
        self,
        exchange_name: str,
        exchange_type: str = 'topic',
        **kwargs
    ) -> None:
        """
        Ensure that the specified exchange exists in RabbitMQ.
        """
        await self.create_exchange(exchange_name, exchange_type, **kwargs)

    async def publish_message(
        self,
        body: Union[str, list, dict, Any],
        queue_name: str,
        routing_key: str,
        **kwargs
    ) -> None:
        """
        Publish a message to a RabbitMQ exchange.
        """
        await self.ensure_connection()
        # Ensure the exchange exists before publishing
        await self.ensure_exchange(queue_name)
        headers = kwargs.get('headers', {})
        headers.setdefault('x-retry', '0')
        args = {
            "mandatory": True,
            "timeout": None,
            **kwargs
        }
        properties_kwargs = {
            'headers': headers,
            'delivery_mode': 2  # Persistent messages
        }
        if isinstance(body, (dict, list)):
            body = json_encoder(body)
            properties_kwargs['content_type'] = 'application/json'
        elif is_dataclass(body) or isinstance(body, BaseModel):
            body = self._serializer.encode(body)
            properties_kwargs['content_type'] = 'application/jsonpickle'
        elif isinstance(body, BaseWrapper):
            body = self._serializer.serialize(body)
            properties_kwargs['content_type'] = 'application/cloudpickle'
        else:
            # Handle other types if necessary
            body = str(body)
            properties_kwargs['content_type'] = 'text/plain'
        try:
            await self._channel.basic_publish(
                body.encode('utf-8'),
                exchange=queue_name,
                routing_key=routing_key,
                properties=aiormq.spec.Basic.Properties(
                    **properties_kwargs
                ),
                **args
            )
        except Exception as exc:
            self.logger.error(
                f"Failed to publish message: {exc}"
            )

    async def process_message(
        self,
        body: bytes,
        properties: aiormq.spec.Basic.Properties
    ) -> str:
        """
        Process the message received by the consumer.
        """
        content_type = properties.content_type or 'text/plain'
        body_str = body.decode('utf-8')
        if content_type == 'application/json':
            try:
                return json_decoder(body_str)
            except ValidationError:
                self.logger.warning(
                    "Error unserializing JSON object."
                )
                return body_str
        elif content_type == 'application/jsonpickle':
            try:
                return self._serializer.decode(body_str)
            except RuntimeError:
                self.logger.warning(
                    "Error deserializing jsonpickle object."
                )
                return body_str
        elif content_type == 'application/cloudpickle':
            try:
                return self._serializer.unserialize(body_str)
            except RuntimeError:
                self.logger.warning(
                    "Error unserializing cloudpickled object."
                )
                return body_str
        elif content_type == 'text/plain':
            return body_str
        else:
            raise RuntimeError(
                f"Unsupported content type: {content_type}"
            )

    def wrap_callback(
        self,
        callback: Callable[[aiormq.abc.DeliveredMessage, str], Awaitable[None]],
        requeue_on_fail: bool = False,
        max_retries: int = 3
    ) -> Callable:
        """
        Wrap the user-provided callback to handle message decoding and
        acknowledgment.
        """
        async def wrapped_callback(message: aiormq.abc.DeliveredMessage):
            try:
                properties = message.header.properties or aiormq.spec.Basic.Properties()
                body = await self.process_message(message.body, properties)
                if asyncio.iscoroutinefunction(callback):
                    await callback(message, body)
                else:
                    callback(message, body)
                # Acknowledge the message to indicate it has been processed
                await self._channel.basic_ack(message.delivery_tag)
                self.logger.debug(
                    f"Message acknowledged: {message.delivery_tag}"
                )
            except Exception as e:
                self.logger.warning(
                    f"Error processing message: {e}"
                )
                # Get retry count from message properties headers
                properties = message.header.properties or aiormq.spec.Basic.Properties()
                headers = dict(properties.headers or {})
                retry_count = headers.get('x-retry', 0)
                # Ensure retry_count is an integer
                if isinstance(retry_count, bytes):
                    retry_count = int(retry_count.decode())
                elif isinstance(retry_count, str):
                    retry_count = int(retry_count)
                else:
                    retry_count = int(retry_count)
                retry_count += 1
                if retry_count <= max_retries:
                    self.logger.info(
                        f"Retrying message {message.delivery_tag}, attempt {retry_count}/{max_retries}"
                    )
                    # Optionally, reject the message and requeue it
                    await self._channel.basic_nack(message.delivery_tag, requeue=False)
                    # Republish the message with incremented retry count
                    new_headers = headers.copy()
                    new_headers['x-retry'] = str(retry_count)
                    new_properties = aiormq.spec.Basic.Properties(
                        content_type=properties.content_type,
                        content_encoding=properties.content_encoding,
                        headers=new_headers,
                        delivery_mode=properties.delivery_mode,
                        priority=properties.priority,
                        correlation_id=properties.correlation_id,
                        reply_to=properties.reply_to,
                        expiration=properties.expiration,
                        message_id=properties.message_id,
                        timestamp=properties.timestamp,
                        message_type=properties.message_type,
                        user_id=properties.user_id,
                        app_id=properties.app_id,
                    )
                    await self._channel.basic_publish(
                        exchange=message.delivery.exchange,
                        routing_key=message.delivery.routing_key,
                        body=message.body,
                        properties=new_properties
                    )
                else:
                    self.logger.error(
                        f"Max retries exceeded for message {message.delivery_tag}. Discarding message."
                    )
                    # Reject the message without requeueing
                    await self._channel.basic_nack(message.delivery_tag, requeue=False)
        return wrapped_callback

    async def consume_messages(
        self,
        queue_name: str,
        callback: Callable[[aiormq.abc.DeliveredMessage, str], Awaitable[None]],
        prefetch_count: int = 1
    ) -> None:
        """
        Consume messages from a queue.
        """
        await self.ensure_connection()
        try:
            # Ensure the queue exists
            await self._channel.queue_declare(queue=queue_name, durable=True)

            # Set QoS (Quality of Service) settings
            await self._channel.basic_qos(prefetch_count=prefetch_count)

            # Start consuming messages from the queue
            await self._channel.basic_consume(
                queue=queue_name,
                consumer_callback=self.wrap_callback(callback),
            )
            self.logger.info(
                f"Started consuming messages from queue '{queue_name}'."
            )
        except Exception as e:
            self.logger.error(
                f"Error consuming messages: {e}"
            )
            raise
