"""Unit tests for NotificationDispatcher + FCMProvider + HMAC webhooks.

Coverage:
- test_dispatcher_all_channels_called: all 5 channels invoked concurrently
- test_dispatcher_fcm_skipped_when_none: FCM channel no-ops when fcm=None
- test_dispatcher_handler_timeout_cancelled: slow handler is cancelled
- test_webhook_hmac_deterministic: sign_payload produces deterministic digest
- test_fcm_provider_token_refresh: FCMProvider refreshes token when expired
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from navigator.ext.geofencing.models import GeofenceTransition, Position, Webhook
from navigator.ext.geofencing.dispatcher import NotificationDispatcher
from navigator.ext.geofencing.webhooks import sign_payload
from navigator.brokers.rabbitmq import MQTTDownlinkPublisher, RMQProducer
from navigator.ext.geofencing.push_providers import PushProvider
from navigator.ext.geofencing.decorators import on_geofence_event, clear_registry


def _make_transition(kind="enter") -> GeofenceTransition:
    return GeofenceTransition(
        employee_id="emp-001",
        geofence_id=1,
        tenant_id="acme",
        kind=kind,
        location=Position(lat=19.43, lng=-99.13, ts=datetime.now(tz=timezone.utc)),
        ts=datetime.now(tz=timezone.utc),
        source_event_id=uuid.uuid4(),
        dwell_duration=None,
    )


@pytest.fixture(autouse=True)
def _clear_handlers():
    clear_registry()
    yield
    clear_registry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_all_channels_called():
    """All five channels are invoked when dispatch() is called."""
    mock_downlink = AsyncMock(spec=MQTTDownlinkPublisher)
    mock_publisher = AsyncMock(spec=RMQProducer)
    mock_fcm = AsyncMock(spec=PushProvider)

    called = {"webhooks": False, "tokens": False}

    async def webhook_loader(t):
        called["webhooks"] = True
        return []

    async def device_tokens(eid):
        called["tokens"] = True
        return ["fake-token"]

    dispatcher = NotificationDispatcher(
        downlink=mock_downlink,
        internal_publisher=mock_publisher,
        fcm=mock_fcm,
        webhook_loader=webhook_loader,
        webhook_decrypt=lambda b: b,
        device_token_lookup=device_tokens,
    )

    try:
        await dispatcher.dispatch(_make_transition())
    finally:
        await dispatcher.aclose()

    mock_downlink.publish_to_employee.assert_called_once()
    mock_publisher.queue_event.assert_called_once()
    mock_fcm.send.assert_called_once()
    # FCM send should be called with device token as first arg
    assert mock_fcm.send.call_args[0][0] == "fake-token"
    assert called["webhooks"]
    assert called["tokens"]


@pytest.mark.asyncio
async def test_dispatcher_fcm_skipped_when_none():
    """FCM channel is silently skipped when fcm=None."""
    mock_downlink = AsyncMock(spec=MQTTDownlinkPublisher)
    mock_publisher = AsyncMock(spec=RMQProducer)

    token_lookup_called = False

    async def device_tokens(eid):
        nonlocal token_lookup_called
        token_lookup_called = True
        return ["token"]

    async def _empty_webhooks(t):
        return []

    dispatcher = NotificationDispatcher(
        downlink=mock_downlink,
        internal_publisher=mock_publisher,
        fcm=None,  # FCM disabled
        webhook_loader=_empty_webhooks,
        webhook_decrypt=lambda b: b,
        device_token_lookup=device_tokens,
    )

    try:
        await dispatcher.dispatch(_make_transition())
    finally:
        await dispatcher.aclose()

    # Device token lookup should NOT be called when fcm is None
    assert not token_lookup_called


@pytest.mark.asyncio
async def test_dispatcher_handler_timeout_cancelled():
    """A slow Python handler is cancelled; other handlers still run."""
    mock_downlink = AsyncMock(spec=MQTTDownlinkPublisher)
    mock_publisher = AsyncMock(spec=RMQProducer)

    fast_called = False

    @on_geofence_event(kind="enter")
    async def slow_handler(t):
        await asyncio.sleep(10)  # much longer than timeout

    @on_geofence_event(kind="enter")
    async def fast_handler(t):
        nonlocal fast_called
        fast_called = True

    async def _empty_webhooks2(t):
        return []

    async def _empty_tokens(eid):
        return []

    dispatcher = NotificationDispatcher(
        downlink=mock_downlink,
        internal_publisher=mock_publisher,
        fcm=None,
        webhook_loader=_empty_webhooks2,
        webhook_decrypt=lambda b: b,
        device_token_lookup=_empty_tokens,
        handler_timeout=0.05,  # 50ms timeout
    )

    try:
        await dispatcher.dispatch(_make_transition())
    finally:
        await dispatcher.aclose()

    # fast_handler should have run despite slow_handler being cancelled
    assert fast_called


@pytest.mark.asyncio
async def test_webhook_hmac_deterministic():
    """sign_payload produces a deterministic HMAC-SHA256 hex digest."""
    body = b'{"a":1,"b":2}'
    secret = b"test-secret-key"
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    result = sign_payload(body, secret)
    assert result == expected
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


@pytest.mark.asyncio
async def test_fcm_provider_token_refresh():
    """FCMProvider refreshes the access token when expired."""
    import time
    from unittest.mock import patch, AsyncMock as AM
    from navigator.ext.geofencing.push_providers.fcm import FCMProvider

    # Minimal fake service account
    fake_sa = {
        "client_email": "test@project.iam.gserviceaccount.com",
        "private_key": "NOT-A-REAL-KEY",
    }

    provider = FCMProvider.__new__(FCMProvider)
    provider._project_id = "test-project"
    provider._session = None
    provider._owns_session = True
    provider._service_account = fake_sa
    provider._access_token = None
    provider._token_expires_at = 0.0
    provider.logger = MagicMock()

    refresh_called = 0

    async def mock_refresh():
        nonlocal refresh_called
        refresh_called += 1
        provider._access_token = "fresh-token"
        provider._token_expires_at = time.time() + 3600

    with patch.object(provider, "_refresh_access_token", side_effect=mock_refresh):
        token = await provider._get_access_token()
        assert token == "fresh-token"
        assert refresh_called == 1

        # Second call should NOT refresh (token not expired)
        token2 = await provider._get_access_token()
        assert token2 == "fresh-token"
        assert refresh_called == 1

        # Force expiry
        provider._token_expires_at = time.time() - 1
        token3 = await provider._get_access_token()
        assert token3 == "fresh-token"
        assert refresh_called == 2
