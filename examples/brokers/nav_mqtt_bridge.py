"""MQTT Bridge + Downlink Example.

Demonstrates how to wire an :class:`EmployeeEventsBridge` (MQTT → AMQP ingest)
alongside a :class:`MQTTDownlinkPublisher` (AMQP → MQTT back-channel) into an
aiohttp web application.

A simple :class:`~navigator.brokers.rabbitmq.RMQConsumer` subscribes to the
republished ``employee.events`` exchange and prints received messages to stdout.

Requirements:
    - A running RabbitMQ 3.12+ instance with the ``rabbitmq_mqtt`` and
      ``rabbitmq_auth_backend_http`` plugins enabled.
    - Navigator configured with ``USE_MQTT_BRIDGE=True`` and valid
      ``RABBITMQ_HOST`` / ``RABBITMQ_USER`` / ``RABBITMQ_PASS`` env vars.

Run:
    $ source .venv/bin/activate
    $ python examples/brokers/nav_mqtt_bridge.py

Expected output (after publishing an MQTT location batch from a test device):
    Bridge started. Listening for employee.events messages...
    Received employee event: {'employee_id': 'emp-001', 'type': 'location.batch', ...}
    [Press Ctrl+C to stop]
"""

from navigator import Application
from navigator.brokers.rabbitmq import (
    EmployeeEventsBridge,
    MQTTDownlinkPublisher,
    RMQConsumer,
)


async def location_event_callback(message, body):
    """Print republished employee location events.

    Args:
        message: Raw aiormq delivered message.
        body: Pre-decoded message body (str or dict).
    """
    print(f"Received employee event: {body}")


app = Application(port=5002)

# MQTT → AMQP ingest bridge
bridge = EmployeeEventsBridge()
bridge.setup(app)

# Downlink publisher (AMQP → MQTT back-channel for sending commands to devices)
downlink = MQTTDownlinkPublisher()
downlink.setup(app)

# Consumer that prints republished messages from the employee.events exchange
consumer = RMQConsumer(
    callback=location_event_callback,
    exchange_name="employee.events",
    queue_name="employee.events.example",
    routing_key="employee.location.updated",
    exchange_type="topic",
)
consumer.setup(app)


if __name__ == "__main__":
    print("Bridge started. Listening for employee.events messages...")
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nEXIT FROM APP =========")
