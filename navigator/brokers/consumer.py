from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Union, Optional, Any
from navconfig.logging import logging


class BrokerConsumer(ABC):
    """
    Broker Consumer Interface.
    """
    _name_: str = "broker_consumer"

    def __init__(
        self,
        callback: Optional[Union[Awaitable, Callable]] = None,
        **kwargs
    ):
        self._queue_name = kwargs.get('queue_name', 'navigator')
        self.logger = logging.getLogger('Broker.Consumer')
        self._callback_ = callback if callback else self.subscriber_callback

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
