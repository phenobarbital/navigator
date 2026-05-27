# TASK-037: NotificationDispatcher — Multi-Channel Fan-Out

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-032, TASK-034, TASK-035, TASK-036
**Assigned-to**: unassigned

---

## Context

Glues the engine, decorator registry, downlink publisher, FCM provider, and
webhook helpers together. Fans out each `GeofenceTransition` to five channels
concurrently with per-handler timeouts and isolated exception handling.

Implements the dispatcher half of **Spec Module 7**.

---

## Scope

Create `navigator/ext/geofencing/dispatcher.py` with `NotificationDispatcher`:

- `__init__(self, *, downlink: MQTTDownlinkPublisher,
  internal_publisher: RMQProducer, fcm: PushProvider | None,
  webhook_loader: Callable[[GeofenceTransition], Awaitable[list[Webhook]]],
  webhook_decrypt: Callable[[bytes], bytes],
  device_token_lookup: Callable[[str], Awaitable[list[str]]],
  geofence_name_resolver: Callable[[int], Optional[str]] | None = None,
  handler_timeout: float = GEOFENCE_HANDLER_TIMEOUT,
  http_session: aiohttp.ClientSession | None = None)`.
- `async dispatch(self, transition: GeofenceTransition) -> None`:
  - Build the canonical payload (`{kind, geofence_id, tenant_id, employee_id,
    ts, location: {lat,lng,ts}, source_event_id, dwell_duration}`).
  - Run five channels concurrently via
    `asyncio.gather(..., return_exceptions=True)`:
    1. **MQTT downlink** — `downlink.publish_to_employee(employee_id,
       "notifications", payload)`.
    2. **FCM push** — `device_token_lookup(employee_id) → [tokens]`; concurrently
       `fcm.send(token, payload)` for each. Skip if `fcm is None`.
    3. **Internal RabbitMQ fanout** — `internal_publisher.queue_event(payload,
       queue_name="geofence.notifications", routing_key="")` (fanout exchanges
       ignore routing key).
    4. **Webhooks** — `webhook_loader(transition)` returns matching
       `Webhook` rows (already filtered by tenant + optional geofence filter);
       concurrently `dispatch_webhook(w, payload, session=self._session,
       decrypt=self._decrypt)` for each.
    5. **Python handlers** — `get_matching_handlers(transition)` (using
       `geofence_name_resolver` if available); each wrapped in
       `asyncio.wait_for(handler(transition), timeout=handler_timeout)` inside
       `asyncio.gather(..., return_exceptions=True)`. Per-handler timeout +
       exception isolation; log per-handler failures, never propagate.
  - Per-channel exceptions logged with channel name; never propagated.
- `async aclose(self) -> None` — closes the internal HTTP session if owned.

**NOT in scope**: registering CRUD routes, building the engine, owning
broker connections at `start()`/`stop()` — TASK-039 owns that.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/dispatcher.py` | CREATE | `NotificationDispatcher` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio, json, logging, time
from collections.abc import Awaitable, Callable
from typing import Optional
import aiohttp

from navigator.conf import GEOFENCE_HANDLER_TIMEOUT
from navigator.brokers.rabbitmq import MQTTDownlinkPublisher, RMQProducer
from navigator.ext.geofencing.models import GeofenceTransition, Webhook
from navigator.ext.geofencing.decorators import get_matching_handlers
from navigator.ext.geofencing.webhooks import dispatch_webhook
from navigator.ext.geofencing.push_providers import PushProvider
```

### Existing Signatures to Use

```python
# TASK-032
class MQTTDownlinkPublisher(RMQProducer):
    async def publish_to_employee(self, employee_id: str, topic: str,
                                  payload: dict) -> None: ...

# TASK-035
def get_matching_handlers(transition: GeofenceTransition) -> list[Callable]: ...

# TASK-036
async def dispatch_webhook(webhook: Webhook, body: dict, *,
                           session: aiohttp.ClientSession,
                           decrypt: Callable[[bytes], bytes],
                           retries: int = 3) -> None: ...

# navigator/brokers/producer.py:108
async def queue_event(self, body, queue_name, routing_key=None, **kwargs) -> None: ...
```

### Does NOT Exist

- ~~A built-in `Webhook` query helper~~ — `webhook_loader` is injected.
- ~~`device_token_lookup` inside the dispatcher~~ — injected; resolves
  `employee_id → list of device tokens` per the existing app model (TASK-039
  wires it).
- ~~APNs channel~~ — out of v1 scope.

### Important Non-Obvious Facts

- The internal RabbitMQ fanout exchange `geofence.notifications` must be of type
  `fanout`. Declare it via `ensure_exchange("geofence.notifications",
  exchange_type="fanout")` at startup (TASK-039 handles startup). The dispatcher
  itself just calls `queue_event`.
- `asyncio.gather(..., return_exceptions=True)` returns exceptions as values —
  iterate the results and `isinstance(r, Exception)` to log per channel.

---

## Acceptance Criteria

- [ ] All five channels are invoked concurrently — wall time ≈ `max(channel
      times)`, not sum.
- [ ] One slow/failing channel does not block the others.
- [ ] Python handler exceeding `GEOFENCE_HANDLER_TIMEOUT` is cancelled; other
      handlers still run.
- [ ] Single handler raising does not block other handlers.
- [ ] FCM skipped cleanly when `fcm is None`.
- [ ] Webhooks filtered by tenant + optional geofence filter via the injected
      `webhook_loader`.
- [ ] `from navigator.ext.geofencing.dispatcher import NotificationDispatcher`
      works.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Skim TASKs 032, 034, 035, 036 outputs.
3. Implement (~150 lines).
4. Smoke-import.
5. Tests deferred to TASK-041.
6. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
