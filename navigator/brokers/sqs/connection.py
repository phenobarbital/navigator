"""
AWS SQS interface (connection and disconnections).
"""
from typing import Optional, Union, Any
from collections.abc import Awaitable, Callable
from dataclasses import is_dataclass
import asyncio
from asyncio import Task
import aioboto3
from datamodel import Model, BaseModel
from navconfig import config
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder, json_decoder
from navigator.exceptions import ValidationError
from ..connection import BaseConnection
from ..wrapper import BaseWrapper


logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("aiobotocore").setLevel(logging.INFO)
logging.getLogger("aioboto3").setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)


class SQSConnection(BaseConnection):
    """
    Manages connection and operations with AWS SQS.
    """

    def __init__(
        self,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        if not credentials:
            credentials = {}
            credentials['aws_access_key_id'] = config.get('AWS_KEY')
            credentials['aws_secret_access_key'] = config.get('AWS_SECRET')
            credentials['region_name'] = config.get('AWS_REGION')
        super().__init__(credentials=credentials, timeout=timeout, **kwargs)
        self._connection = None
        self._session = None
        self.consumer_task: Optional[Task] = None

    async def connect(self):
        """
        Establish connection with AWS SQS.
        """
        if self._connection:
            return
        try:
            self.logger.info("Connecting to AWS SQS...")
            self._session = aioboto3.Session()
            async with self._session.resource(
                "sqs",
                **self._credentials
            ) as sqs_resource:
                self._connection = sqs_resource
            self.logger.info("Connected to AWS SQS.")
        except Exception as e:
            self.logger.error(
                f"Failed to connect to AWS SQS: {e}"
            )
            raise

    async def disconnect(self):
        """
        Disconnect from AWS SQS and explicitly close the aiohttp session.
        """
        self.logger.info("Disconnecting from AWS SQS...")
        if self._connection:
            try:
                # Explicitly close the aiohttp session used by the connection
                await self._connection.meta.client.close()
            except Exception as e:
                self.logger.error(f"Error closing client session: {e}")
        self._connection = None
        self._session = None
        self.logger.info("Disconnected from AWS SQS.")

    async def create_queue(self, queue_name: str, attributes: Optional[dict] = None):
        """
        Create a queue in AWS SQS.
        """
        try:
            self.logger.info(f"Creating queue '{queue_name}'...")
            queue = await self._connection.create_queue(
                QueueName=queue_name,
                Attributes=attributes or {}
            )
            self._queues[queue_name] = queue
            self.logger.info(f"SQS Queue '{queue_name}' created.")
            return queue
        except Exception as e:
            self.logger.error(f"Failed to create queue '{queue_name}': {e}")
            raise

    async def ensure_queue(self, queue_name: str, attributes: Optional[dict] = None):
        """
        Ensure the specified queue exists in AWS SQS. Create it if it doesn't.
        """
        if queue_name in self._queues:
            return self._queues[queue_name]

        try:
            self.logger.info(f"Checking if queue '{queue_name}' exists...")
            # Try to get the queue by name
            queue = await self._connection.get_queue_by_name(QueueName=queue_name)
            self._queues[queue_name] = queue
            self.logger.info(f"Queue '{queue_name}' exists.")
            return queue
        except self._connection.meta.client.exceptions.QueueDoesNotExist:
            self.logger.warning(f"Queue '{queue_name}' does not exist. Creating it...")
            try:
                # If the queue does not exist, create it
                queue = await self.create_queue(queue_name, attributes)
                return queue
            except Exception as e:
                self.logger.error(f"Failed to create queue '{queue_name}': {e}")
                raise

    async def publish_message(
        self,
        body: Union[str, list, dict, Any],
        queue_name: str,
        **kwargs
    ):
        """
        Publish a message to the specified queue.
        """
        try:
            queue = await self.ensure_queue(queue_name)
            message_attributes = kwargs.get('attributes', {})

            # Determine serialization method based on the type of 'body'
            if isinstance(body, (int, float, bool, None.__class__)):
                # Use msgpack for primitives
                body = self._serializer.pack(body)
                message_attributes["ContentType"] = {"StringValue": "application/msgpack", "DataType": "String"}
            elif isinstance(body, bytes):
                # Use msgpack for raw bytes
                body = self._serializer.pack(body)
                message_attributes["ContentType"] = {"StringValue": "application/msgpack", "DataType": "String"}
            elif isinstance(body, (dict, list)):
                # Use JSON for dictionaries
                body = json_encoder(body)
                message_attributes["ContentType"] = {"StringValue": "application/json", "DataType": "String"}
            elif is_dataclass(body) or isinstance(body, (Model, BaseModel)):
                # JSONPickle serialization for dataclasses or BaseModel
                body = self._serializer.serialize(body)
                message_attributes["ContentType"] = {"StringValue": "application/cloudpickle", "DataType": "String"}
            elif isinstance(body, BaseWrapper):
                # CloudPickle serialization for BaseWrapper
                body = self._serializer.serialize(body)
                message_attributes["ContentType"] = {"StringValue": "application/cloudpickle", "DataType": "String"}
            elif hasattr(body, "__class__") and not isinstance(body, (str, bytes)):
                # CloudPickle serialization for other custom objects
                body = self._serializer.serialize(body)
                message_attributes["ContentType"] = {"StringValue": "application/cloudpickle", "DataType": "String"}
            else:
                # Fallback to plain text for str and other simple types
                body = str(body)
                message_attributes["ContentType"] = {"StringValue": "text/plain", "DataType": "String"}

            await queue.send_message(
                MessageBody=body,
                MessageAttributes=message_attributes,
            )
            self.logger.info(
                f"Message published to queue '{queue_name}'."
            )
        except Exception as e:
            self.logger.error(
                f"Failed to publish message to queue '{queue_name}': {e}"
            )
            raise

    async def process_message(self, body: str, attributes: dict):
        """
        Process the message received by the consumer.
        """
        try:
            content_type = attributes.get("ContentType", {}).get("StringValue", "text/plain")
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
            return body
        except Exception as e:
            self.logger.error(
                f"Failed to process message: {e}"
            )
            raise

    def wrap_callback(
        self,
        callback: Callable[[dict, str], Awaitable[None]],
    ) -> Callable[[Any], Awaitable[None]]:
        """
        Wraps the user-provided callback for message handling.
        """

        async def wrapped_callback(message):
            try:
                # Await the message attributes
                body = await message.body
                attributes = await message.message_attributes or {}
                message_id = await message.message_id

                # Process the message body and pass it to the callback
                processed_message = await self.process_message(body, attributes)
                if asyncio.iscoroutinefunction(callback):
                    await callback(message, processed_message)
                else:
                    callback(message, processed_message)

                # Log message ID and acknowledge (delete) the message
                self.logger.info(f"Processed Message ID: {message_id}")
                await message.delete()  # Acknowledge message
                self.logger.info(f"Message acknowledged: {message_id}")
            except Exception as e:
                self.logger.error(f"Error processing message: {e}")

        return wrapped_callback

    async def consume_messages(
        self,
        queue_name: str,
        callback: Callable[[dict, str], Awaitable[None]],
        max_messages: int = 10,
        wait_time: int = 10,
        idle_sleep: int = 5,
    ):
        """
        Consume messages from the specified queue and process them with the callback.
        Handles shutdown signals gracefully.
        """
        try:
            queue = await self.ensure_queue(queue_name)
            while True:
                messages = await queue.receive_messages(
                    MessageAttributeNames=["All"],
                    MaxNumberOfMessages=max_messages,
                    WaitTimeSeconds=wait_time,
                )
                if not messages:
                    self.logger.info("No messages in queue. Sleeping briefly...")
                    await asyncio.sleep(idle_sleep)
                    continue

                for message in messages:
                    wrapped_callback = self.wrap_callback(callback)
                    await wrapped_callback(message)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.logger.info("Message consumption cancelled. Cleaning up...")
            raise
        except Exception as e:
            self.logger.error(f"Error consuming messages from queue '{queue_name}': {e}")
            raise

    async def consume_message(
        self,
        queue_name: str,
        callback: Union[Callable, Awaitable[None]] = None,
        wait_time: int = 5,
    ) -> Optional[dict]:
        """
        Consume a single message from the specified queue.

        Args:
            queue_name (str): The name of the queue to consume a message from.
            callback (Callable, optional): An optional callback function to process the message.
            wait_time (int): The wait time for long polling (default: 5 seconds).

        Returns:
            Optional[dict]: The processed message, or None if no message is available.
        """
        try:
            # Ensure the queue exists
            queue = await self.ensure_queue(queue_name)

            # Receive a single message with long polling
            messages = await queue.receive_messages(
                MessageAttributeNames=["All"],
                MaxNumberOfMessages=1,
                WaitTimeSeconds=wait_time,
            )

            if not messages:
                self.logger.info("No messages available in the queue.")
                return None

            # Process the first message
            message = messages[0]
            body = await message.body
            attributes = await message.message_attributes or {}

            processed_message = await self.process_message(body, attributes)

            # Optionally invoke a callback with the processed message
            if callback:
                if asyncio.iscoroutinefunction(callback):
                    await callback(processed_message, body)
                else:
                    callback(processed_message, body)

            # Delete the message from the queue
            await message.delete()
            self.logger.info(
                f"Message consumed and deleted from queue '{queue_name}'."
            )

            return processed_message
        except Exception as e:
            self.logger.error(
                f"Error consuming a single message from queue '{queue_name}': {e}"
            )
            raise
