# TASK-031: EmployeeEventsBridge — MQTT-Plugin Ingestion Bridge

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-029
**Assigned-to**: unassigned

---

## Context

The bridge consumes MQTT-originated AMQP messages from `amq.topic` /
`employees.#`, dedups by `eventId`, validates `schemaVersion`, enforces
envelope/JWT `employeeId` consistency, fans batched `positions[]` into per-position
AMQP messages, and republishes to the domain `employee.events` topic exchange.

Implements **Spec Module 3**: Ingestion Bridge.

---

## Scope

Create `navigator/brokers/rabbitmq/bridge.py` exporting
`EmployeeEventsBridge(RMQConsumer)`:

- `__init__(self, *, dedup_ttl=MQTT_EVENT_DEDUP_TTL,
  dedup_redis_url=MQTT_EVENT_DEDUP_REDIS_URL,
  accepted_schema_versions=MQTT_ACCEPTED_SCHEMA_VERSIONS,
  max_batch_size=MQTT_MAX_BATCH_SIZE,
  enforce_employee_id=MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY,
  employee_events_exchange=EMPLOYEE_EVENTS_EXCHANGE, **kwargs)`. Defaults pull from
  `navigator.conf` (so production runs with the spec-blessed values; tests can
  inject).
- Override `start(self, app)` to call `subscribe_to_events(exchange="amq.topic",
  queue_name="employee.events.ingest", routing_key="employees.#",
  callback=self._handle_envelope, exchange_type="topic")`.
- `async _handle_envelope(self, message: aiormq.abc.DeliveredMessage, body)`:
  - `body` is already JSON-decoded by `RabbitMQConnection.process_message`
    (`navigator/brokers/rabbitmq/connection.py:238`); guard for `dict` shape.
  - Extract `eventId`, `employeeId`, `type`, `schemaVersion`,
    `positions`/`payload`, `timestamp`.
  - Validate envelope fields (DLQ + structured WARNING on parse error).
  - **Dedup**: `await self._redis.set(name=f"mqtt:dedup:{eventId}",
    value="1", ex=dedup_ttl, nx=True)`. If returns falsy (key already exists),
    skip republish (log DEBUG).
  - **Schema check**: `if schemaVersion not in accepted_schema_versions:` →
    publish to `employee.events.dlq.schema` with original body + reason header.
  - **employeeId enforcement** (when `enforce_employee_id=True`): read MQTT user
    from `message.header.properties.user_id`; mismatch → DLQ + WARNING with
    `mqtt_username`, `envelope_employee_id`, `eventId`, source IP (best-effort
    from message headers).
  - **Routing**:
    - `type == "location.batch"`:
      - `len(positions) == 0` → DLQ.
      - `len(positions) > max_batch_size` → DLQ.
      - For each `idx, position in enumerate(positions)`:
        - Per-position dedup: `set f"mqtt:dedup:{eventId}:{idx}"` with same TTL,
          `nx=True`; skip if hit.
        - Publish to `employee_events_exchange` with routing key
          `employee.location.updated`, body
          `{employeeId, lat, lng, ts, tenantId?}`, headers `{eventId,
          positionIndex: idx, batchSize: len(positions), tenantId?}`.
    - `type == "status"` → key `employee.status.updated`, body `payload`.
    - `type == "events.check-in"` → key `employee.checkin.recorded`.
    - `type == "events.incidents"` → key `employee.incident.created`.
    - Unknown `type` → DLQ.
- **Redis failure handling**: catch connection errors from the dedup call, log
  WARNING, **proceed with republish** (fail-open per spec §1 Constraint 5a).
- Lazy Redis client: build it in `connect()` (override or `start()`) so importing
  this module is cheap; use `redis.asyncio.from_url(dedup_redis_url)`.
- DLQ helper `async _to_dlq(self, body: bytes, reason: str, kind: str)` that
  publishes to `employee.events.dlq.{kind}` (`schema`, `envelope`, `batch_size`,
  `empty_batch`, `employee_id_mismatch`, `unknown_type`).

**NOT in scope**: downlink (TASK-032), engine (TASK-034), dispatcher, CRUD, extension
wiring. This task lives entirely in `navigator/brokers/rabbitmq/bridge.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/brokers/rabbitmq/bridge.py` | CREATE | `EmployeeEventsBridge(RMQConsumer)` |
| `navigator/brokers/rabbitmq/__init__.py` | MODIFY (append) | `from .bridge import EmployeeEventsBridge` re-export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional, Union
from collections.abc import Callable, Awaitable
import aiormq
from redis.asyncio import from_url as redis_from_url        # available via existing redis dep
from navconfig.logging import logging
from navigator.brokers.rabbitmq.consumer import RMQConsumer  # navigator/brokers/rabbitmq/consumer.py:19
from navigator.conf import (
    MQTT_EVENT_DEDUP_TTL, MQTT_EVENT_DEDUP_REDIS_URL,
    MQTT_ACCEPTED_SCHEMA_VERSIONS, MQTT_MAX_BATCH_SIZE,
    MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY,
    EMPLOYEE_EVENTS_EXCHANGE,
)
```

### Existing Signatures to Use

```python
# navigator/brokers/rabbitmq/consumer.py:19
class RMQConsumer(RabbitMQConnection, BrokerConsumer):
    _name_: str = "rabbitmq_consumer"
    def __init__(self, credentials=None, timeout=5, callback=None, **kwargs): ...
    async def subscribe_to_events(self, exchange, queue_name, routing_key,
                                  callback, exchange_type='topic', durable=True,
                                  prefetch_count=1, requeue_on_fail=True,
                                  max_retries=3, **kwargs) -> None: ...   # :78
    async def start(self, app: web.Application) -> None: ...               # :127

# navigator/brokers/rabbitmq/connection.py
class RabbitMQConnection(BaseConnection):
    async def ensure_exchange(self, exchange_name, exchange_type='topic',
                              **kwargs) -> None: ...                       # :175
    async def publish_message(self, body, queue_name, routing_key,
                              **kwargs) -> None: ...                       # :186
        # 'queue_name' here is actually the EXCHANGE name (legacy naming).
        # The bridge republishes via this signature.
    async def process_message(self, body: bytes,
                              properties) -> str: ...                       # :238
        # Decodes JSON when content_type is 'application/json'.

# aiormq message shape — message.body, message.header.properties.user_id,
# message.delivery.routing_key, message.delivery.exchange
```

### Does NOT Exist

- ~~`navigator/brokers/rabbitmq/bridge.py`~~ — CREATE in this task.
- ~~`employee.events` exchange~~ — declare it via `ensure_exchange` on `start()`.
- ~~`employee.events.dlq.*` exchanges~~ — declare on first DLQ publish.
- ~~A pre-built dedup helper~~ — implement inline; do not invent a util module.
- ~~`MQTT_JWT_SECRET`~~ — JWT validation lives in `navigator_auth`; the bridge
  trusts `message.header.properties.user_id` because the MQTT plugin populates
  it from the JWT-authenticated MQTT username.

### Important Non-Obvious Facts

- `RMQConsumer.start()` (`:127`) currently auto-subscribes using
  `self._exchange_name`/`self._queue_name`/`self._routing_key`. Either override
  `start()` entirely OR set the consumer's three kwargs at init time. Overriding
  is clearer because the bridge always uses fixed values.
- `publish_message`'s first positional kwarg `queue_name` is actually the
  exchange name. Pass `queue_name=EMPLOYEE_EVENTS_EXCHANGE` for the republish path.
- The MQTT plugin's `user_id` propagation requires RabbitMQ 3.12+ — flagged in
  spec §7 Risks; runbook in TASK-040 documents this.

---

## Acceptance Criteria

- [ ] `EmployeeEventsBridge` subscribes to `amq.topic` / `employees.#` on
      `start(app)`.
- [ ] Duplicate `eventId` → republish skipped (Redis SET NX miss path).
- [ ] Per-position dedup uses `{eventId}:{positionIndex}` keys.
- [ ] Redis down → WARNING logged, republish proceeds (fail-open).
- [ ] `schemaVersion` not in `MQTT_ACCEPTED_SCHEMA_VERSIONS` → DLQ
      `employee.events.dlq.schema`.
- [ ] Envelope `employeeId` ≠ `message.properties.user_id` → DLQ
      `employee.events.dlq.employee_id_mismatch` + structured WARNING containing
      `mqtt_username`, `envelope_employee_id`, `eventId`.
- [ ] `type=location.batch` with `positions=[p1,p2,p3]` produces three messages on
      `EMPLOYEE_EVENTS_EXCHANGE` with key `employee.location.updated`, each
      carrying `eventId` + `positionIndex` + `batchSize` headers.
- [ ] `len(positions) > MQTT_MAX_BATCH_SIZE` → DLQ.
- [ ] Empty `positions[]` → DLQ.
- [ ] Non-batch types map to correct routing keys
      (`status` → `employee.status.updated`, etc.).
- [ ] `from navigator.brokers.rabbitmq import EmployeeEventsBridge` works
      (re-exported from package `__init__.py`).
- [ ] Module import is cheap when `USE_MQTT_BRIDGE=False` — Redis client built
      lazily in `start()`, not at module load.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Read `navigator/brokers/rabbitmq/consumer.py:19-142` and
   `navigator/brokers/rabbitmq/connection.py:175-237` end-to-end.
3. Implement the bridge.
4. Smoke-import: `python -c "from navigator.brokers.rabbitmq import EmployeeEventsBridge"`.
5. Defer tests to TASK-041.
6. Update index; move file on completion.

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-05-27
**Notes**:
**Deviations from spec**: none | describe if any
