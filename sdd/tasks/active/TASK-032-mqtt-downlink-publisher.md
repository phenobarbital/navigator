# TASK-032: MQTTDownlinkPublisher — AMQP→MQTT-Plugin Downlink

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-029
**Assigned-to**: unassigned

---

## Context

The dispatcher needs a way to publish on `amq.topic` with routing key
`employees.{employee_id}.{topic}`. The RabbitMQ MQTT plugin auto-delivers this
to MQTT subscribers — no MQTT client required.

Implements **Spec Module 4**: MQTT Downlink Publisher.

---

## Scope

Create `navigator/brokers/rabbitmq/downlink.py` exporting
`MQTTDownlinkPublisher(RMQProducer)`:

- `_name_: str = "mqtt_downlink_publisher"`.
- `__init__(self, credentials=None, queue_size=None, num_workers=4, timeout=5,
  **kwargs)` — pass-through to `RMQProducer.__init__`.
- `async publish_to_employee(self, employee_id: str, topic: str, payload: dict)
  -> None` — enqueues a publish via `self.queue_event(body=payload,
  queue_name="amq.topic", routing_key=f"employees.{employee_id}.{topic}")`. The
  parent's worker drains the queue and calls `publish_message` for actual delivery.
- No new transport logic; the existing
  `RabbitMQConnection.publish_message`/`process_message` already handle
  JSON serialization (`navigator/brokers/rabbitmq/connection.py:186, :238`).

Add to `navigator/brokers/rabbitmq/__init__.py` (after the bridge import added by
TASK-031):
```python
from .downlink import MQTTDownlinkPublisher
```

**NOT in scope**: bridge, dispatcher, engine, CRUD. Just the thin publisher.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/brokers/rabbitmq/downlink.py` | CREATE | `MQTTDownlinkPublisher(RMQProducer)` |
| `navigator/brokers/rabbitmq/__init__.py` | MODIFY | Re-export `MQTTDownlinkPublisher` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional, Union
from navconfig.logging import logging
from navigator.brokers.rabbitmq.producer import RMQProducer   # exists; re-exported via package __init__.py
```

### Existing Signatures to Use

```python
# navigator/brokers/rabbitmq/producer.py
class RMQProducer(BrokerProducer, RabbitMQConnection):
    _name_: str = "rabbitmq_producer"
    def __init__(self, credentials, queue_size=None, num_workers=4, timeout=5, **kwargs): ...

# navigator/brokers/producer.py:108
async def queue_event(self, body, queue_name, routing_key=None, **kwargs) -> None: ...
    # Enqueues onto BrokerProducer's asyncio.Queue; worker drains via
    # publish_message at navigator/brokers/producer.py:254.

# navigator/brokers/rabbitmq/connection.py:186
async def publish_message(self, body, queue_name, routing_key, **kwargs) -> None: ...
    # Auto-JSON-encodes dict/list bodies (sets content_type=application/json).
```

### Does NOT Exist

- ~~`navigator/brokers/rabbitmq/downlink.py`~~ — CREATE in this task.
- ~~A bespoke `publish_to_mqtt(...)` on `RabbitMQConnection`~~ — do NOT add one.
  All downlink goes through the queue/worker pattern of `BrokerProducer`.

### Important Non-Obvious Facts

- `amq.topic` is built into RabbitMQ; do **not** redeclare it with a different
  type. `ensure_exchange("amq.topic", exchange_type="topic")` is idempotent
  (it already exists with the right type).
- The RabbitMQ MQTT plugin delivers AMQP messages on `amq.topic` /
  `employees.123.notifications` to MQTT subscribers of
  `employees/123/notifications`. This bidirectionality is the entire reason
  Option A works.

---

## Acceptance Criteria

- [ ] `MQTTDownlinkPublisher.publish_to_employee("123", "notifications",
      {"k":"v"})` results in an AMQP message on `amq.topic` with routing key
      `employees.123.notifications` after a worker drains the queue.
- [ ] `from navigator.brokers.rabbitmq import MQTTDownlinkPublisher` works.
- [ ] Smoke-import is cheap (does not connect to RabbitMQ at import time).
- [ ] No new transport, serializer, or retry logic introduced — everything is
      inherited from `RMQProducer` / `RabbitMQConnection`.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/brokers/producer.py:16-130` (parent `__init__`, `setup`,
   `queue_event`).
3. Implement the thin subclass (~40 lines including docstrings).
4. Smoke-import.
5. Tests deferred to TASK-041.
6. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
