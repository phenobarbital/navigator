from navigator import Application
from navigator.brokers.rabbitmq import RMQConsumer


async def rabbit_callback(*args, **kwargs):
    # Handle your SQS callback here
    print('Received Message:', args, kwargs)

app = Application(
    port=5001
)

rmq = RMQConsumer(
    callback=rabbit_callback
)
rmq.setup(app)

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
