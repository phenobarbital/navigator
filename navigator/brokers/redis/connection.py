"""
Redis interface (connection and disconnections) using Redis Streams.
"""
from typing import Optional, Union, Any, Dict
from collections.abc import Awaitable, Callable
import time
import asyncio
from dataclasses import is_dataclass
from redis import asyncio as aioredis
from datamodel import Model, BaseModel
from navconfig.logging import logging
from navigator.libs.json import json_encoder, json_decoder
from navigator.exceptions import ValidationError
from ..connection import BaseConnection
from ..wrapper import BaseWrapper
from ...conf import (
    REDIS_BROKER_HOST,
    REDIS_BROKER_PORT,
    REDIS_BROKER_PASSWORD,
    REDIS_BROKER_DB,
    REDIS_BROKER_URL
)

class RedisConnection(BaseConnection):
    """
    Manages connection and operations with Redis using Redis Streams.
    """
    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        self._name_ = self.__class__.__name__
        if not credentials:
            credentials = {}
            credentials['host'] = REDIS_BROKER_HOST
            credentials['port'] = REDIS_BROKER_PORT
            credentials['password'] = REDIS_BROKER_PASSWORD
            credentials['db'] = REDIS_BROKER_DB
        super().__init__(credentials=credentials, timeout=timeout, **kwargs)
        self._connection: Optional[aioredis.Redis] = None
        self.logger = logging.getLogger('RedisConnection')
        self._group_name = kwargs.get('group_name', 'default_group')
        self._consumer_name = kwargs.get('consumer_name', 'default_consumer')
        self._queue_name = kwargs.get('queue_name', 'message_stream')

    async def connect(self):
        """
        Establish connection with Redis.
        """
        if self._connection:
            return
        try:
            self.logger.info("Connecting to Redis...")
            self._connection = aioredis.Redis(
                **self._credentials,
                decode_responses=True,
                encoding='utf-8'
            )
            # Ensure that the group exists
            await self.ensure_group_exists()
            self.logger.info("Connected to Redis.")
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def ensure_connection(self) -> None:
        """
        Ensures that the connection is active.
        """
        if self._connection is None:
            await self.connect()

    async def disconnect(self):
        """
        Disconnect from Redis.
        """
        self.logger.info("Disconnecting from Redis...")
        if self._connection:
            try:
                await self._connection.close()
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")
        self._connection = None
        self.logger.info("Disconnected from Redis.")

    async def ensure_group_exists(self):
        """
        Ensure the consumer group exists for the stream.
        """
        try:
            # Create the stream if it doesn't exist
            stream_exists = await self._connection.exists(self._queue_name)
            if not stream_exists:
                await self._connection.xadd(self._queue_name, {'initial': 'message'})
            # Try to create the group. This will fail if the group already exists.
            await self._connection.xgroup_create(
                name=self._queue_name,
                groupname=self._group_name,
                id='0',
                mkstream=True
            )
            self.logger.info(f"Group '{self._group_name}' created on stream '{self._queue_name}'.")
        except aioredis.ResponseError as e:
            if "BUSYGROUP Consumer Group name already exists" in str(e):
                self.logger.info(
                    f"Group '{self._group_name}' already exists."
                )
            else:
                self.logger.error(
                    f"Error creating group '{self._group_name}': {e}"
                )
                raise
        try:
            # create the consumer:
            await self._connection.xgroup_createconsumer(
                self._queue_name, self._group_name, self._consumer_name
            )
            self.logger.debug(
                f":: Creating Consumer {self._consumer_name} on Stream {self._queue_name}"
            )
        except Exception as exc:
            self.logger.exception(exc, stack_info=True)
            raise

    async def publish_message(
        self,
        body: Union[str, list, dict, Any],
        queue_name: Optional[str] = None,
        **kwargs
    ):
        """
        Publish a message to the specified Redis Stream.
        """
        stream = queue_name or self._queue_name
        try:
            message_data = {}
            # Determine serialization method based on the type of 'body'
            if isinstance(body, (int, float, bool, None.__class__)):
                # Use msgpack for primitives
                packed_body = self._serializer.pack(body)
                content_type = "application/msgpack"
            elif isinstance(body, bytes):
                # Use msgpack for raw bytes
                packed_body = self._serializer.pack(body)
                content_type = "application/msgpack"
            elif isinstance(body, (dict, list)):
                # Use JSON for dictionaries
                packed_body = json_encoder(body)
                content_type = "application/json"
            elif is_dataclass(body) or isinstance(body, (Model, BaseModel)):
                # JSONPickle serialization for dataclasses or BaseModel
                packed_body = self._serializer.serialize(body)
                content_type = "application/cloudpickle"
            elif isinstance(body, BaseWrapper):
                # CloudPickle serialization for BaseWrapper
                packed_body = self._serializer.serialize(body)
                content_type = "application/cloudpickle"
            elif hasattr(body, "__class__") and not isinstance(body, (str, bytes)):
                # CloudPickle serialization for other custom objects
                packed_body = self._serializer.serialize(body)
                content_type = "application/cloudpickle"
            else:
                # Fallback to plain text for str and other simple types
                packed_body = str(body)
                content_type = "text/plain"

            # TODO: add base64 encoding for binary data
            message_data['body'] = packed_body
            message_data['ContentType'] = content_type

            await self._connection.xadd(stream, message_data, nomkstream=False)
            self.logger.info(f"Message published to stream '{stream}'.")
        except Exception as e:
            self.logger.error(f"Failed to publish message to stream '{stream}': {e}")
            raise

    async def process_message(self, message_data: Dict[bytes, bytes]):
        """
        Process the message received by the consumer.
        """
        body = message_data.get('body')
        content_type = message_data.get('ContentType', 'text/plain')
        try:
            if content_type == 'application/json':
                return json_decoder(body)
            elif content_type == "application/msgpack":
                return self._serializer.unpack(body)
            elif content_type == 'application/jsonpickle':
                try:
                    return self._serializer.decode(body)
                except Exception as e:
                    self.logger.error(f"Error decoding JSONPickle message: {e}")
                    return body
            elif content_type == 'application/cloudpickle':
                return self._serializer.unserialize(body)
            elif content_type == 'text/plain':
                return body
            else:
                self.logger.warning(
                    f"Unknown content type: {content_type}. Returning raw body."
                )
                return body
        except ValidationError:
            self.logger.warning("Error decoding message.")
            return message_data.get(b'body')
        except Exception as e:
            self.logger.error(f"Failed to process message: {e}")
            raise

    async def consume_messages(
        self,
        queue_name: Optional[str],
        callback: Callable[[Dict[str, Any], str], Awaitable[None]],
        count: int = 1,
        block: int = 1000,
        **kwargs
    ):
        """
        Consume messages from the specified Redis Stream and process them with the callback.
        """
        stream = queue_name or self._queue_name
        consumer_name = kwargs.get('consumer_name', self._consumer_name)
        try:
            # Clean up old messages before starting
            await self.cleanup_old_messages(stream)
            while True:
                response = await self._connection.xreadgroup(
                    groupname=self._group_name,
                    consumername=consumer_name,
                    streams={stream: '>'},
                    count=count,
                    block=block
                )
                if not response:
                    await asyncio.sleep(1)
                    continue
                for _, messages in response:
                    for message_id, message_data in messages:
                        try:
                            processed_message = await self.process_message(message_data)
                            data = {
                                "message_id": message_id,
                                "data": message_data
                            }
                            if asyncio.iscoroutinefunction(callback):
                                await callback(data, processed_message)
                            else:
                                callback(data, processed_message)
                            # Acknowledge the message
                            await self._connection.xack(stream, self._group_name, message_id)
                            self.logger.info(
                                f"Message {message_id} acknowledged."
                            )
                        except Exception as e:
                            self.logger.error(
                                f"Error processing message {message_id}: {e}"
                            )
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.logger.info(
                "Message consumption cancelled. Cleaning up..."
            )
            raise
        except Exception as e:
            self.logger.error(f"Error consuming messages from stream '{stream}': {e}")
            raise

    async def cleanup_old_messages(self, stream):
        """Removes messages older than 7 days from the stream."""
        try:
            # Calculate the timestamp for 7 days ago
            seven_days_ago = int((time.time() - 7 * 24 * 60 * 60) * 1000)
            # Convert it to a Redis Stream ID format (timestamp-part-sequence)
            seven_days_ago_id = f"{seven_days_ago}-0"
            # Use XTRIM with minid to remove messages older than the calculated timestamp
            await self._connection.xtrim(stream, minid=seven_days_ago_id)
            self.logger.info(
                f"Cleaned up old messages from stream {stream}"
            )
        except Exception as e:
            self.logger.error(
                f"Error cleaning up old messages: {e}"
            )
