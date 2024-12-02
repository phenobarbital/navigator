from navigator import Application
from navigator.brokers.sqs import SQSConsumer


async def sqs_callback(*args, **kwargs):
    # Handle your SQS callback here
    print('Received Message:', args, kwargs)

app = Application(
    port=5001
)

sqs = SQSConsumer(
    callback=sqs_callback
)
sqs.setup(app)

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
