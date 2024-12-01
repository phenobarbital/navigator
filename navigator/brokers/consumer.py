from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Union, Optional, Any
from aiohttp import web
from navconfig.logging import logging
from navigator.applications.base import BaseApplication
from .connection import BaseConnection


class BrokerConsumer(BaseConnection, ABC):
    """
    Broker Consumer Interface.
    """
    _name_: str = "broker_consumer"

    def __init__(
        self,
        credentials: Union[str, dict],
        timeout: Optional[int] = 5,
        callback: Optional[Union[Awaitable, Callable]] = None,
        **kwargs
    ):
        self._queue_name = kwargs.get('queue_name', 'navigator')
        super(BrokerConsumer, self).__init__(credentials, timeout, **kwargs)
        self.logger = logging.getLogger('Broker.Consumer')
        self._callback_ = callback if callback else self.subscriber_callback

    @abstractmethod
    async def connect(self):
        """
        Connect to Broker.
        """
        pass

    @abstractmethod
    async def disconnect(self):
        """
        Disconnect from Broker.
        """
        pass

    async def start(self, app: web.Application) -> None:
        await self.connect()

    async def stop(self, app: web.Application) -> None:
        # close the RabbitMQ connection
        await self.disconnect()

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

    @abstractmethod
    async def event_subscribe(
        self,
        queue_name: str,
        callback: Union[Callable, Awaitable]
    ) -> None:
        """
        Subscribe to a Queue and consume messages.
        """
        pass

    @abstractmethod
    async def subscriber_callback(
        self,
        message: Any,
        body: str
    ) -> None:
        """
        Default Callback for Event Subscription.
        """
        pass

    @abstractmethod
    def wrap_callback(
        self,
        callback: Callable[[Any, str], Awaitable[None]],
        requeue_on_fail: bool = False,
        max_retries: int = 3
    ) -> Callable:
        """
        Wrap the user-provided callback to handle message decoding and
        acknowledgment.
        """
