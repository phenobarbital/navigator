# TASK-040: Ops Runbook + Bridge & Geofencing Examples

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-039
**Assigned-to**: unassigned

---

## Context

Operators need a runbook to enable the RabbitMQ MQTT/auth/web plugins,
configure TLS, and apply rate-limit policies. Developers need a working example.

Implements **Spec Module 11**: Ops Docs & Examples.

---

## Scope

Create three artifacts:

### 1. `docs/ops/rabbitmq-mqtt.md`

Sections:
- **Plugins to enable**:
  ```bash
  rabbitmq-plugins enable rabbitmq_mqtt rabbitmq_web_mqtt rabbitmq_auth_backend_http
  ```
- **`rabbitmq.conf` example** showing:
  - MQTT TCP listener on 1883 (dev) and TLS listener on 8883 (prod).
  - `auth_backends.1 = http` with `auth_http.user_path`, `vhost_path`,
    `resource_path`, `topic_path` pointing at Navigator's `/api/v1/mqtt/auth/*`.
  - `auth_http.http_method = post`.
  - Per-connection rate-limit policy (`policy.mqtt-rate.pattern = "amq.topic"`,
    `policy.mqtt-rate.definition.max-publishing-rate = ...`,
    `max-connections-per-user`).
- **RabbitMQ version requirement**: 3.12+ (so MQTT plugin propagates
  `user_id` on AMQP republish for the bridge's `employeeId` enforcement).
- **TLS cert provisioning** quick checklist (does not duplicate the org's cert
  authority docs — just notes where to point the listener).
- **Navigator config keys** matrix (the keys added by TASK-029) with
  recommended dev vs prod defaults.
- **`MQTT_JWT_SECRET` is intentionally NOT a Navigator config key** — JWT
  signing lives in `navigator_auth`; this is a security feature, not an
  omission.
- **Troubleshooting**:
  - Bridge DLQ paths and how to inspect (`employee.events.dlq.{schema,
    envelope, batch_size, empty_batch, employee_id_mismatch, unknown_type}`).
  - How to verify `user_id` propagation (publish from a test MQTT client and
    inspect the AMQP message via `rabbitmqadmin get`).

### 2. `examples/brokers/nav_mqtt_bridge.py`

Mirrors `examples/brokers/nav_rabbitmq_consumer.py` but constructs an
`EmployeeEventsBridge` + a `MQTTDownlinkPublisher`, wires them into an
`aiohttp.web.Application`, and shows a print-to-stdout consumer for the
republished messages on `employee.events`.

### 3. `examples/geofencing/basic_geofence.py`

Demonstrates:
- Creating a `GeofencingExtension` with mock `app_db` / encrypt / decrypt /
  device-token lookup (so the example runs against a fresh RabbitMQ + SQLite
  / in-memory DB).
- Defining a polygon via CRUD (`POST /api/v1/geofencing/fences`).
- Registering `@on_geofence_event(geofence_name="store_42", kind="enter")` and
  `@on_geofence_event(kind="dwell")` handlers that print to stdout.
- Publishing a synthetic location batch to `amq.topic /
  employees.123.location` to trigger the pipeline end-to-end.

Each example must include a top docstring with:
```
$ source .venv/bin/activate
$ python examples/geofencing/basic_geofence.py
# Expected output: ...
```

**NOT in scope**: code changes outside `docs/` and `examples/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/ops/rabbitmq-mqtt.md` | CREATE | Ops runbook |
| `examples/brokers/nav_mqtt_bridge.py` | CREATE | Bridge + downlink example |
| `examples/geofencing/basic_geofence.py` | CREATE | End-to-end geofencing example |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (for examples)

```python
from aiohttp import web
from navigator.brokers.rabbitmq import (
    EmployeeEventsBridge, MQTTDownlinkPublisher, RMQConsumer,
)
from navigator.ext.geofencing import (
    GeofencingExtension, on_geofence_event, GeofenceTransition,
)
```

### Existing References to Mirror

- `examples/brokers/nav_rabbitmq_consumer.py` — pattern for example file layout
  (top-of-file docstring, `setup(app)`, `web.run_app(app)`).

### Does NOT Exist

- ~~`docs/ops/rabbitmq-mqtt.md`~~ — CREATE.
- ~~`examples/geofencing/`~~ — CREATE the directory.
- ~~A canonical example DB layer~~ — use SQLite via `aiosqlite` or in-memory
  fixtures; do NOT pull in a real DB driver.

### Important Non-Obvious Facts

- The runbook should be plain Markdown — no Mermaid; the rendered platform may
  not support it.
- The example's mock `secret_encrypt`/`secret_decrypt` may be identity
  functions (`lambda b: b`) — flag in the docstring that this is example-only.

---

## Acceptance Criteria

- [ ] `docs/ops/rabbitmq-mqtt.md` covers all sections listed in Scope.
- [ ] Runbook states the RabbitMQ 3.12+ requirement and the
      `MQTT_JWT_SECRET`-not-a-key rationale.
- [ ] `examples/brokers/nav_mqtt_bridge.py` boots an aiohttp app and prints
      republished messages when run against a local RabbitMQ-with-MQTT-plugin.
- [ ] `examples/geofencing/basic_geofence.py` runs end-to-end against a local
      RabbitMQ + a mock DB, printing handler invocations on enter/dwell.
- [ ] Both example files include reproducible run instructions in their docstring.

---

## Agent Instructions

1. Skim `examples/brokers/nav_rabbitmq_consumer.py` for shape.
2. Write the runbook + two examples.
3. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
