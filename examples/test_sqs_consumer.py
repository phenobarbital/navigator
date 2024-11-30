import asyncio
from navconfig import config
from navigator.brokers.sqs import SQSConnection
import pandas as pd

AWS_ACCESS_KEY = config.get('AWS_KEY')
AWS_SECRET_KEY = config.get('AWS_SECRET')
AWS_REGION = config.get('AWS_REGION')


async def example_callback(message, processed_message):
    # print(f"Processed Message: {processed_message}")
    # print(f"Type: {type(processed_message)}")
    # print(f"Raw Message: {message}")
    metadata = processed_message.get('metadata')
    print(metadata)
    payload = processed_message.get('payload')
    print('PAYLOAD > ', payload)
    df = pd.DataFrame([payload])
    print(df)


async def main():
    connection = SQSConnection(
        credentials={
            "aws_access_key_id": AWS_ACCESS_KEY,
            "aws_secret_access_key": AWS_SECRET_KEY,
            "region_name": AWS_REGION
        }
    )
    async with connection as sqs:
        await sqs.consume_messages("MainEvent", example_callback)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
