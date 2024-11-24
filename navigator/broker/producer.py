"""
RabbitMQ Producer Module.

can be used to send messages to RabbitMQ.
"""
from typing import Any, Optional
from collections.abc import Callable, Awaitable
import asyncio
from functools import wraps
from aiohttp import web
from navconfig.logging import logging
from navconfig.utils.types import Singleton
from navigator.applications.base import BaseApplication
from navigator_session import get_session
from navigator_auth.conf import (
    AUTH_SESSION_OBJECT
)
from ..conf import BROKER_MANAGER_QUEUE_SIZE
from .rabbit import RabbitMQConnection
from .pickle import DataSerializer


# Disable Debug Logging for AIORMQ
logging.getLogger('aiormq').setLevel(logging.INFO)


class BrokerManager(RabbitMQConnection, metaclass=Singleton):
    """BrokerManager.

    BrokerManager is the Producer functionality for RabbitMQ using aiormq.


    Args:

    """
    _name_: str = "broker_manager"
    __initialized__: bool = False

    def __init__(
        self,
        dsn: Optional[str] = None,
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        if self.__initialized__ is True:
            return
        self.queue_size = queue_size if queue_size else BROKER_MANAGER_QUEUE_SIZE
        self.app: Optional[BaseApplication] = None
        self.timeout: int = timeout
        self.logger = logging.getLogger('BrokerManager')
        self.event_queue = asyncio.Queue(maxsize=self.queue_size)
        self._num_workers = num_workers
        self._workers = []
        super(BrokerManager, self).__init__(dsn, timeout, **kwargs)
        self.__initialized__ = True
        self._serializer = DataSerializer()

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
        self.app.on_startup.append(self.open)
        self.app.on_shutdown.append(self.close)
        self.app[self._name_] = self
        ## Generic Event Subscription:
        self.app.router.add_post(
            '/api/v1/broker/events/publish_event',
            self.event_publisher
        )
        self.logger.notice(
            ":: Starting RabbitMQ Producer ::"
        )

    async def start_workers(self):
        for i in range(self._num_workers):
            task = asyncio.create_task(
                self._event_broker(i)
            )
            self._workers.append(task)

    async def _event_broker(self, worker_id: int):
        """
        Creates a Publisher event publisher.
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
                routing = event.get('routing_key')
                exchange = event.get('exchange')
                body = event.get('body')
                max_retries = event.get('max_retries', 5)
                retry_count = 0
                retry_delay = 1
                while True:
                    try:
                        # Publish the event to RabbitMQ
                        await self.publish_message(
                            exchange_name=exchange,
                            routing_key=routing,
                            body=body
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

    async def open(self, app: web.Application) -> None:
        """Signal Function to be called when the application is started.

        Connect to RabbitMQ, starts the Queue and start publishing.
        """
        await self.connect()
        # Start the Queue workers
        await self.start_workers()

    async def close(self, app: web.Application) -> None:
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

        # then, close the RabbitMQ connection
        await self.disconnect()

    async def queue_event(
        self,
        exchange: str,
        routing_key: str,
        body: str,
        **kwargs
    ) -> None:
        """
        Puts an Event into the Queue to be processed for Producer later.
        """
        try:
            self.event_queue.put_nowait(
                {
                    'exchange': exchange,
                    'routing_key': routing_key,
                    'body': body,
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
        exchange: str,
        routing_key: str,
        body: str,
        **kwargs
    ) -> None:
        """
        Publish Event on a rabbitMQ Exchange.
        """
        # Ensure the exchange exists before publishing
        await self.publish_message(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
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
        exc = data.get('exchange', 'navigator')
        routing_key = data.get('routing_key')
        if not routing_key:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'routing_key is required.'
                },
                status=422
            )
        body = data.get('body')
        if not body:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'Message Body for Broker is required.'
                },
                status=422
            )
        try:
            await self.queue_event(exc, routing_key, body)
            return web.json_response({
                'status': 'success',
                'message': f'Event {exc}.{routing_key} Published Successfully.'
            })
        except asyncio.QueueFull:
            return web.json_response(
                {
                    'status': 'error',
                    'message': 'Event queue is full. Please try again later.'
                },
                status=429
            )
