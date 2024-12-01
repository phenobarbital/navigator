"""
RabbitMQ Producer Module.

can be used to send messages to RabbitMQ.
"""
from typing import Union, Optional
from navconfig.logging import logging
from .connection import RabbitMQConnection
from .producer import BrokerProducer


# Disable Debug Logging for AIORMQ
logging.getLogger('aiormq').setLevel(logging.INFO)

class RMQProducer(BrokerProducer, RabbitMQConnection):
    """RMQProducer.

    RMQProducer is the Producer functionality for RabbitMQ using aiormq.

    Args:
        dsn: RabbitMQ DSN.
        queue_size: Size of Asyncio Queue for enqueuing messages before send.
        num_workers: Number of workers to process the queue.
        timeout: Timeout for RabbitMQ Connection.
    """
    _name_: str = "rabbitmq_producer"

    def __init__(
        self,
        credentials: Union[str, dict],
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        super(RMQProducer, self).__init__(
            credentials=credentials,
            queue_size=queue_size,
            num_workers=num_workers,
            timeout=timeout,
            **kwargs
        )
