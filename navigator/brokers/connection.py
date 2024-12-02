"""
Base Abstract for all Broker Service connections.
"""
from typing import Optional, Union, Any
from collections.abc import Awaitable, Callable
from abc import ABC, abstractmethod
import asyncio
from aiohttp import web
from navconfig.logging import logging
from navigator.applications.base import BaseApplication
from .pickle import DataSerializer


class BaseConnection(ABC):
    """
    Manages connection and operations over Broker Services.
    """

    def __init__(
        self,
        *args,
        credentials: Union[str, dict] = None,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        self._credentials = credentials
        self._timeout: int = timeout
        self._connection = None
        self._monitor_task: Optional[Awaitable] = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._queues: dict = {}
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = kwargs.get(
            'max_reconnect_attempts', 3
        )
        self.reconnect_delay = 1  # Initial delay in seconds
        self._lock = asyncio.Lock()
        self._serializer = DataSerializer()
        super().__init__(*args, **kwargs)

    def get_connection(self) -> Optional[Union[Callable, Awaitable]]:
        if not self._connection:
            raise RuntimeError('No connection established.')
        return self._connection

    def get_serializer(self) -> DataSerializer:
        return self._serializer

    async def __aenter__(self) -> 'BaseConnection':
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    @abstractmethod
    async def connect(self) -> None:
        """
        Creates a Connection to Broker Service.
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from Broker Service.
        """
        raise NotImplementedError

    async def ensure_connection(self) -> None:
        """
        Ensures that the connection is active.
        """
        if self._connection is None:
            await self.connect()

    @abstractmethod
    async def publish_message(
        self,
        body: Union[str, list, dict, Any],
        queue_name: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Publish a message to the Broker Service.
        """
        raise NotImplementedError

    @abstractmethod
    async def consume_messages(
        self,
        queue_name: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Consume messages from the Broker Service.
        """
        raise NotImplementedError

    @abstractmethod
    async def process_message(
        self,
        body: bytes,
        properties: Any
    ) -> str:
        """
        Process a message from the Broker Service.
        """
        raise NotImplementedError

    async def start(self, app: web.Application) -> None:
        await self.connect()

    async def stop(self, app: web.Application) -> None:
        # close the RabbitMQ connection
        await self.disconnect()

    def setup(self, app: web.Application = None) -> None:
        """
        Setup Broker Connection.
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
