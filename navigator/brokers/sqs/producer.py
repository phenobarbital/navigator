"""
RabbitMQ Producer Module.

can be used to send messages to RabbitMQ.
"""
from typing import Union, Optional
from .connection import SQSConnection
from ..producer import BrokerProducer


class SQSProducer(SQSConnection, BrokerProducer):
    """SQSProducer.

    SQSProducer is the Producer functionality for Message Queue using AWS SQS.

    Args:
        credentials: AWS Credentials.
        queue_size: Size of Asyncio Queue for enqueuing messages before send.
        num_workers: Number of workers to process the queue.
        timeout: Timeout for RabbitMQ Connection.
    """
    _name_: str = "sqs_producer"

    def __init__(
        self,
        credentials: Union[str, dict],
        queue_size: Optional[int] = None,
        num_workers: Optional[int] = 4,
        timeout: Optional[int] = 5,
        **kwargs
    ):
        super(SQSProducer, self).__init__(
            credentials=credentials,
            queue_size=queue_size,
            num_workers=num_workers,
            timeout=timeout,
            **kwargs
        )
