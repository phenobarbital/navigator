# TASK-041: Unit & Integration Tests (MQTT Bridge + Geofencing)

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (8h+)
**Depends-on**: TASK-030, TASK-031, TASK-032, TASK-034, TASK-035, TASK-036, TASK-037, TASK-038, TASK-039
**Assigned-to**: unassigned

---

## Context

Realizes the Test Specification section of the spec. Covers all units listed in
spec §4 plus the five integration scenarios. Integration tests are
CI-conditional (require a RabbitMQ container with MQTT plugin); mark with
`pytest.mark.integration`.

Implements **Spec Module 12**: Tests.

---

## Scope

Create:

- `tests/handlers/test_mqtt_auth.py` — 6 tests covering the rows in spec §4
  prefixed `test_mqtt_auth_*`.
- `tests/brokers/test_mqtt_bridge.py` — 11 tests covering `test_bridge_*` and
  `test_downlink_*` rows in spec §4.
- `tests/ext/geofencing/test_engine.py` — 11 tests covering `test_engine_*` rows.
- `tests/ext/geofencing/test_decorators.py` — 3 tests covering `test_decorator_*`.
- `tests/ext/geofencing/test_dispatcher.py` — 4 tests covering `test_dispatcher_*`
  and the `test_webhook_hmac_*` + `test_fcm_provider_*` rows.
- `tests/ext/geofencing/test_crud.py` — 3 tests covering `test_crud_*` rows.
- `tests/integration/test_mqtt_e2e.py` — 5 tests covering spec §4 Integration
  Tests table. Marked `pytest.mark.integration`; skipped when
  `RABBITMQ_MQTT_TEST_DSN` env var is unset.

Use the fixtures listed in spec §4 (`sample_envelope_batch`,
`sample_tenant_geofences`, `fake_redis_dedup`). Add a shared
`tests/ext/geofencing/conftest.py` for the engine and dispatcher fixtures.

Mock external services:
- Redis dedup → in-memory dict.
- aiohttp outbound calls (FCM, webhooks) → `aresponses` or
  `aiohttp.test_utils.TestServer`.
- DB → `aiosqlite` in-memory or a stub `db` object with the methods CRUD uses.
- RabbitMQ for unit tests → mock the `RMQConsumer`/`RMQProducer` superclass
  methods (`publish_message`, `subscribe_to_events`, `queue_event`); for
  integration tests, run against the env-supplied DSN.

**NOT in scope**: code under test. Bug fixes discovered while writing tests go
back to the originating task (commit message: `sdd: tests reveal bug in TASK-<N>`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_mqtt_auth.py` | CREATE | MQTT auth handler tests |
| `tests/brokers/test_mqtt_bridge.py` | CREATE | Bridge + downlink tests |
| `tests/ext/geofencing/__init__.py` | CREATE | Empty package marker |
| `tests/ext/geofencing/conftest.py` | CREATE | Shared fixtures |
| `tests/ext/geofencing/test_engine.py` | CREATE | Engine tests |
| `tests/ext/geofencing/test_decorators.py` | CREATE | Decorator registry tests |
| `tests/ext/geofencing/test_dispatcher.py` | CREATE | Dispatcher + FCM + webhook tests |
| `tests/ext/geofencing/test_crud.py` | CREATE | CRUD tests |
| `tests/integration/__init__.py` | CREATE (if missing) | Empty package marker |
| `tests/integration/test_mqtt_e2e.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest, asyncio, json, hmac, hashlib
from unittest.mock import AsyncMock, MagicMock, patch
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestServer, TestClient
```

### Existing Test Patterns

- Check `tests/` (if it exists) for the repo's pytest convention; mirror
  the existing async test style (`pytest_asyncio.fixture`, `@pytest.mark.asyncio`).

### Does NOT Exist

- ~~An existing test fixture for the MQTT bridge / engine~~ — write fresh.
- ~~A `pytest.mark.mqtt_integration` mark~~ — use generic
  `pytest.mark.integration`.

### Important Non-Obvious Facts

- Engine tests must include the **point ordering trap**: `Point(lng, lat)`
  vs `Point(lat, lng)`. Add an explicit fixture that uses real-world
  coordinates (e.g., Mexico City 19.43,-99.13) and asserts the polygon contains
  it — flips the bug detection visible.
- Dwell-timer tests should `monkeypatch` `asyncio.get_running_loop().call_later`
  to a fast-forward shim, OR use `pytest-asyncio` with `event_loop_policy` and
  `asyncio.sleep(small_value)` with a temporarily-low `GEOFENCE_DWELL_DURATION`
  override. Real wall-clock 5-minute waits in tests are unacceptable.
- HMAC determinism: assert the hex digest equals a hand-computed value, not
  just "is a hex string of length 64".

---

## Acceptance Criteria

- [ ] All unit tests pass: `pytest tests/handlers/test_mqtt_auth.py
      tests/brokers/test_mqtt_bridge.py tests/ext/geofencing/ -v`.
- [ ] Integration tests skip cleanly when `RABBITMQ_MQTT_TEST_DSN` is unset:
      `pytest tests/integration/ -v` runs zero tests in skip mode.
- [ ] Coverage matrix matches spec §4 (every row in both Unit Tests and
      Integration Tests tables has a corresponding test function).
- [ ] No real wall-clock waits for dwell timers (`< 1s` per test).
- [ ] No real FCM or webhook HTTP calls during unit tests (all mocked).
- [ ] No tests touch `MQTT_JWT_SECRET` (it does not exist).

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. `ls tests/` to see the existing layout and pytest fixtures available.
3. Write tests per the matrix.
4. Run `pytest tests/handlers tests/brokers tests/ext/geofencing -v` and
   iterate until green.
5. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
