from dataclasses import dataclass
import asyncio
from datamodel import BaseModel
from navconfig import config
from navigator.brokers.sqs import SQSConnection

AWS_ACCESS_KEY = config.get('AWS_KEY')
AWS_SECRET_KEY = config.get('AWS_SECRET')
AWS_REGION = config.get('AWS_REGION')


@dataclass
class Example:
    name: str
    age: int

class ExampleModel(BaseModel):
    name: str
    age: int

async def main():
    connection = SQSConnection(
        credentials={
            "aws_access_key_id": AWS_ACCESS_KEY,
            "aws_secret_access_key": AWS_SECRET_KEY,
            "region_name": AWS_REGION
        }
    )
    async with connection as sqs:
        # Create an SQS Queue
        queue_name = "navigator"
        print(f"Creating queue: {queue_name}")
        queue = await sqs.create_queue(queue_name)
        queue_url = queue.url
        print(f"Queue URL: {queue_url}")

        # # Publish a JSON Message
        # await sqs.publish_message({"key": "value"}, "MyTestQueue")
        # # Publish JSONPickle
        # model = ExampleModel(name="John Doe", age=30)
        # await sqs.publish_message(model, "MyTestQueue")
        # # Dataclasses:
        # mdl = Example(name="John Doe", age=30)
        # await sqs.publish_message(mdl, "MyTestQueue")

        # # Publish CloudPickle
        # class CustomWrapper:
        #     def __init__(self, data):
        #         self.data = data

        # wrapper = CustomWrapper(data={"nested_key": "nested_value"})
        # await sqs.publish_message(wrapper, "MyTestQueue")

        form = {
            "metadata": {
                "type": "recapDefinition",
                "transactionType": "UPSERT",
                "source": "MainEvent",
                "client": "global"
            },
            "payload": {
                "formid": 7,
                "form_name": "Assembly Tech Form",
                "active": True,
                "created_on": "2024-09-24T07:13:20-05:00",
                "updated_on": "2024-09-25T12:51:53-05:00",
                "is_store_stamp": False,
                "client_id": 61,
                "client_name": "ASSEMBLY",
                "orgid": 71
            }
        }
        # Publish plain text
        await sqs.publish_message(form, "navigator")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
