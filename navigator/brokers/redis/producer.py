"""
Redis Producer Module.

can be used to send messages to Redis Streams.
"""
from typing import Union, Optional
from .connection import RedisConnection
from ..producer import BrokerProducer


class RedisProducer(RedisConnection, BrokerProducer):
    """RedisProducer.

    RedisProducer is the Producer functionality for Message Queue using Redis Streams.

    Args:
        credentials: dictionary of redis credentials.
        queue_size: Size of Asyncio Queue for enqueuing messages before send.
        num_workers: Number of workers to process the queue.
        timeout: Timeout for Redis Connection.
    """
    _name_: str = "redis_producer"

    def __init__(
        self,
        credentials: Union[str, dict],
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        super(RedisProducer, self).__init__(
            credentials=credentials,
            queue_size=queue_size,
            num_workers=num_workers,
            timeout=timeout,
            **kwargs
        )
