"""Unit tests for EmployeeEventsBridge + MQTTDownlinkPublisher.

Coverage:
- test_bridge_valid_batch_processed: valid location.batch is fanned out
- test_bridge_invalid_schema_version: wrong schemaVersion → DLQ schema
- test_bridge_missing_envelope_fields: missing required fields → DLQ envelope
- test_bridge_batch_too_large: batch > max → DLQ batch_size
- test_bridge_empty_batch: empty positions → DLQ empty_batch
- test_bridge_employee_id_mismatch: AMQP user_id ≠ envelope employeeId → DLQ
- test_bridge_dedup_skips_duplicate: second event with same eventId is skipped
- test_bridge_unknown_type: unknown type → DLQ unknown_type
- test_bridge_redis_fail_open: Redis error → message still processed
- test_bridge_status_routed: status event routed to employee.status.updated
- test_downlink_routing_key: publish_to_employee builds correct routing key
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from navigator.brokers.rabbitmq.bridge import EmployeeEventsBridge
from navigator.brokers.rabbitmq.downlink import MQTTDownlinkPublisher


def _make_message(user_id: str = "emp-001") -> MagicMock:
    """Return a mock aiormq DeliveredMessage with user_id property.

    The bridge accesses ``message.header.properties.user_id``.
    user_id is a plain string as the bridge compares with str().
    """
    props = MagicMock()
    props.user_id = user_id  # plain str; bridge uses str(mqtt_username)
    header = MagicMock()
    header.properties = props
    msg = MagicMock()
    msg.header = header
    return msg


def _make_bridge(**kwargs) -> EmployeeEventsBridge:
    """Return an EmployeeEventsBridge without RabbitMQ connection."""
    bridge = EmployeeEventsBridge.__new__(EmployeeEventsBridge)
    bridge._dedup_ttl = 600
    bridge._dedup_redis_url = "redis://localhost:6379"
    bridge._accepted_schema_versions = {1}
    bridge._max_batch_size = 200
    bridge._enforce_employee_id = kwargs.get("enforce_employee_id", True)
    bridge._employee_events_exchange = "employee.events"
    bridge._redis = None
    bridge.logger = MagicMock()
    return bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_valid_batch_processed(fake_redis_dedup, sample_envelope_batch):
    """Valid location.batch envelope fans out positions to employee.events."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    published = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        published.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, sample_envelope_batch)

    # Two positions → two publishes
    assert len(published) == 2
    for body, exchange, rk in published:
        assert exchange == "employee.events"
        assert rk == "employee.location.updated"


@pytest.mark.asyncio
async def test_bridge_invalid_schema_version(fake_redis_dedup):
    """Wrong schemaVersion sends message to DLQ schema."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 99,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [{"lat": 19.43, "lng": -99.13, "ts": "2026-01-01T00:00:00Z"}],
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    # Should land in the schema DLQ
    assert any("schema" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_missing_envelope_fields(fake_redis_dedup):
    """Missing required fields sends to DLQ envelope."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    # Missing employeeId
    envelope = {
        "schemaVersion": 1,
        "type": "location.batch",
        "positions": [{"lat": 19.43, "lng": -99.13}],
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any("envelope" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_batch_too_large(fake_redis_dedup):
    """Position batch exceeding max_batch_size sends to DLQ batch_size."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    bridge._max_batch_size = 2
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [{"lat": 1, "lng": 1, "ts": "2026-01-01T00:00:00Z"}] * 5,
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any("batch_size" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_empty_batch(fake_redis_dedup):
    """Empty positions array sends to DLQ empty_batch."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [],
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any("empty_batch" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_employee_id_mismatch(fake_redis_dedup):
    """AMQP user_id different from envelope employeeId → DLQ employee_id_mismatch."""
    bridge = _make_bridge(enforce_employee_id=True)
    bridge._redis = fake_redis_dedup
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-999",  # mismatch with message user_id "emp-001"
        "type": "location.batch",
        "positions": [{"lat": 1, "lng": 1, "ts": "2026-01-01T00:00:00Z"}],
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any("employee_id_mismatch" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_dedup_skips_duplicate(fake_redis_dedup):
    """Second event with the same eventId is deduplicated and dropped."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    published = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        published.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    event_id = str(uuid.uuid4())
    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [{"lat": 19.43, "lng": -99.13, "ts": "2026-01-01T00:00:00Z"}],
        "eventId": event_id,
    }
    msg = _make_message("emp-001")
    # First call: processed
    await bridge._handle_envelope(msg, dict(envelope))
    first_count = len(published)
    assert first_count == 1

    # Second call with same eventId: should be deduplicated
    await bridge._handle_envelope(msg, dict(envelope))
    assert len(published) == first_count  # no new publishes


@pytest.mark.asyncio
async def test_bridge_unknown_type(fake_redis_dedup):
    """Unknown type sends to DLQ unknown_type."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    dlq_messages = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        dlq_messages.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "unknown.custom.type",
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any("unknown_type" in str(q) for _, q, _ in dlq_messages)


@pytest.mark.asyncio
async def test_bridge_redis_fail_open():
    """Redis error does not block message processing (fail-open)."""
    bridge = _make_bridge()

    class _FailingRedis:
        async def set(self, **kwargs):
            raise ConnectionError("Redis unreachable")

    bridge._redis = _FailingRedis()
    published = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        published.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "location.batch",
        "positions": [{"lat": 19.43, "lng": -99.13, "ts": "2026-01-01T00:00:00Z"}],
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    # Message should still be published despite Redis failure
    assert len(published) == 1


@pytest.mark.asyncio
async def test_bridge_status_routed(fake_redis_dedup):
    """status type event is routed to employee.status.updated."""
    bridge = _make_bridge()
    bridge._redis = fake_redis_dedup
    published = []

    async def mock_publish(body, queue_name, routing_key, **kwargs):
        published.append((body, queue_name, routing_key))

    bridge.publish_message = mock_publish
    bridge.ensure_exchange = AsyncMock()

    envelope = {
        "schemaVersion": 1,
        "employeeId": "emp-001",
        "type": "status",
        "payload": {"status": "active"},
        "eventId": str(uuid.uuid4()),
    }
    msg = _make_message("emp-001")
    await bridge._handle_envelope(msg, envelope)

    assert any(rk == "employee.status.updated" for _, _, rk in published)


@pytest.mark.asyncio
async def test_downlink_routing_key():
    """publish_to_employee builds routing key employees.{id}.{topic}."""
    import logging
    downlink = MQTTDownlinkPublisher.__new__(MQTTDownlinkPublisher)
    downlink.logger = logging.getLogger("test_downlink")
    queued = []

    async def mock_queue_event(body, queue_name, routing_key):
        queued.append((body, queue_name, routing_key))

    downlink.queue_event = mock_queue_event

    payload = {"kind": "enter"}
    await downlink.publish_to_employee("emp-123", "notifications", payload)

    assert len(queued) == 1
    body, exchange, rk = queued[0]
    assert rk == "employees.emp-123.notifications"
    assert exchange == "amq.topic"
    assert body == payload
