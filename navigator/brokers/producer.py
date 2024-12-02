from abc import ABC
from typing import Awaitable, Callable, Union, Optional, Any
import asyncio
from functools import wraps
from aiohttp import web
from navconfig.logging import logging
from navigator_session import get_session
from navigator_auth.conf import (
    AUTH_SESSION_OBJECT
)
from navigator.applications.base import BaseApplication
from .connection import BaseConnection
from ..conf import BROKER_MANAGER_QUEUE_SIZE


class BrokerProducer(BaseConnection, ABC):
    """
    Broker Producer Interface.

    Args:
        credentials: Message Queue Credentials.
        queue_size: Size of Asyncio Queue for enqueuing messages before send.
        num_workers: Number of workers to process the queue.
        timeout: Timeout for MQ Connection.

    """
    _name_: str = "broker_producer"

    def __init__(
        self,
        credentials: Union[str, dict],
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        self.queue_size = queue_size if queue_size else BROKER_MANAGER_QUEUE_SIZE
        self.app: Optional[BaseApplication] = None
        self.timeout: int = timeout
        self.logger = logging.getLogger('Broker.Producer')
        self.event_queue = asyncio.Queue(maxsize=self.queue_size)
        self._num_workers = num_workers
        self._workers = []
        self._broker_service: str = kwargs.get('broker_service', 'rabbitmq')
        super(BrokerProducer, self).__init__(credentials, timeout, **kwargs)

    def setup(self, app: web.Application = None) -> None:
        """
        Setup BrokerManager.
        """
        if isinstance(app, BaseApplication):
            self.app = app.get_app()
        else:
            self.app = app
        if self.app is None:
            raise ValueError(
                'App is not defined.'
            )
        # Initialize the Producer instance.
        self.app.on_startup.append(self.start)
        self.app.on_shutdown.append(self.stop)
        self.app[self._name_] = self
        ## Generic Event Subscription:
        self.app.router.add_post(
            f'/api/v1/broker/{self._broker_service}/publish_event',
            self.event_publisher
        )
        self.logger.notice(
            ":: Starting Message Queue Producer ::"
        )

    async def start_workers(self):
        """
        Start the Queue workers.
        """
        for i in range(self._num_workers):
            task = asyncio.create_task(
                self._event_broker(i)
            )
            self._workers.append(task)

    async def start(self, app: web.Application) -> None:
        """Signal Function to be called when the application is started.

        Connect to Message Queue, starts the Queue and start publishing.
        """
        await self.connect()
        # Start the Queue workers
        await self.start_workers()

    async def stop(self, app: web.Application) -> None:
        # Wait for all events to be processed
        await self.event_queue.join()

        # Cancel worker tasks
        for task in self._workers:
            try:
                task.cancel()
            except asyncio.CancelledError:
                pass

        # Wait for worker tasks to finish
        await asyncio.gather(*self._workers, return_exceptions=True)

        # then, close the Message Queue connection
        await self.disconnect()

    async def queue_event(
        self,
        body: str,
        queue_name: str,
        routing_key: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Puts an Event into the Queue to be processed for Producer later.
        """
        try:
            self.event_queue.put_nowait(
                {
                    'body': body,
                    'queue_name': queue_name,
                    'routing_key': routing_key,
                    **kwargs
                }
            )
            await asyncio.sleep(.1)
        except asyncio.QueueFull:
            self.logger.error(
                "Event queue is full. Event will not published."
            )
            raise

    async def publish_event(
        self,
        body: str,
        queue_name: str,
        **kwargs
    ) -> None:
        """
        Publish Event on a Message Queue Exchange.
        """
        # Ensure the exchange exists before publishing
        await self.publish_message(
            body=body,
            queue_name=queue_name,
            **kwargs
        )

    # Event Publisher: POST API for dispatching events to RabbitMQ.
    async def get_userid(self, session, idx: str = 'user_id') -> int:
        try:
            if AUTH_SESSION_OBJECT in session:
                return session[AUTH_SESSION_OBJECT][idx]
            else:
                return session[idx]
        except KeyError:
            raise RuntimeError(
                'User ID is not found in the session.'
            )

    @staticmethod
    def service_auth(
        fn: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[Any]]:
        @wraps(fn)
        async def _wrap(self, request: web.Request, *args, **kwargs) -> Any:
            ## get User Session:
            try:
                session = await get_session(request)
            except (ValueError, RuntimeError) as err:
                raise web.HTTPUnauthorized(
                    reason=str(err)
                )
            if session:
                self._userid = await self.get_userid(session)
            # Perform your session and user ID checks here
            if not self._userid:
                raise web.HTTPUnauthorized(
                    reason="User ID not found in session"
                )
            # TODO: Checking User Permissions:
            return await fn(self, request, *args, **kwargs)
        return _wrap

    @service_auth
    async def event_publisher(
        self,
        request: web.Request
    ) -> web.Response:
        """
        Event Publisher.

        Uses as an REST API to send events to RabbitMQ.
        """
        data = await request.json()
        qs = data.pop('queue_name', 'navigator')
        routing_key = data.pop('routing_key', None)
        if not routing_key:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'routing_key is required.'
                },
                status=422
            )
        body = data.pop('body')
        if not body:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'Message Body for Broker is required.'
                },
                status=422
            )
        try:
            await self.queue_event(body, qs, routing_key, **data)
            return web.json_response({
                'status': 'success',
                'message': f'Event {qs}.{routing_key} Published Successfully.'
            })
        except asyncio.QueueFull:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'Event queue is full. Please try again later.'
                },
                status=429
            )

    async def _event_broker(self, worker_id: int):
        """
        Creates an Event publisher.
        Worker function to publish events from the queue to RabbitMQ.

        will check if there is something available in the temporal queue.
        Queue is used to avoid losing things if the publisher is not ready.
        Implements backpressure handling by retrying failed publishes.
        """
        while True:
            # Wait for an event to be available in the queue
            event = await self.event_queue.get()
            try:
                # data:
                routing = event.pop('routing_key')
                queue_name = event.pop('queue_name')
                body = event.pop('body')
                max_retries = event.pop('max_retries', 5)
                retry_count = 0
                retry_delay = 1
                while True:
                    try:
                        # Publish the event to RabbitMQ
                        await self.publish_message(
                            body=body,
                            queue_name=queue_name,
                            routing_key=routing,
                            **event
                        )
                        self.logger.info(
                            f"Worker {worker_id} published event: {routing}"
                        )
                        # TODO: Optionally, add the event to a dead-letter queue
                        # await self.dead_letter_queue.put(event)
                        break  # Exit the retry loop on success
                    except Exception as e:
                        retry_count += 1
                        if retry_count >= max_retries:
                            self.logger.error(
                                f"Worker {worker_id} failed to publish event: {e}"
                            )
                            break  # Exit the retry loop on max retries
                        self.logger.warning(
                            f"Worker {worker_id} failed to publish event: {e}. "
                            f"Retrying in {retry_delay} seconds..."
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
            except Exception as e:
                self.logger.error(
                    f"Error publishing event: {e}"
                )
            finally:
                self.event_queue.task_done()
