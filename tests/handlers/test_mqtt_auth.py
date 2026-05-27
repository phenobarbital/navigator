"""Unit tests for MQTT auth handlers.

Coverage:
- test_mqtt_auth_user_valid: valid JWT returns 'allow tags=management'
- test_mqtt_auth_user_invalid: invalid token returns 'deny'
- test_mqtt_auth_vhost_valid_vhost: valid vhost returns 'allow'
- test_mqtt_auth_resource_authenticated: authenticated user allowed resource
- test_mqtt_auth_topic_own_employee: employee can access own topic
- test_mqtt_auth_topic_other_employee: employee cannot access other's topic
"""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

import navigator.handlers.mqtt_auth as mqtt_auth_mod
from navigator.handlers.mqtt_auth import (
    mqtt_auth_user,
    mqtt_auth_vhost,
    mqtt_auth_resource,
    mqtt_auth_topic,
    _CACHE,
)


def _make_request(post_data: dict) -> MagicMock:
    """Return a mock aiohttp request with the given POST data."""
    request = MagicMock()
    request.post = AsyncMock(return_value=post_data)
    return request


@pytest.fixture(autouse=True)
def clear_auth_cache():
    """Clear the auth cache before each test."""
    _CACHE.clear()
    yield
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mqtt_auth_user_valid():
    """Valid JWT token returns 'allow tags=management'."""
    fake_payload = {"sub": "emp-001", "employee_id": "emp-001"}

    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=fake_payload)):
        request = _make_request({
            "username": "emp-001",
            "password": "valid.jwt.token",
            "vhost": "/",
        })
        response = await mqtt_auth_user(request)

    assert "allow" in response.text
    assert response.content_type == "text/plain"


@pytest.mark.asyncio
async def test_mqtt_auth_user_invalid():
    """Invalid JWT token (None payload) returns 'deny'."""
    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=None)):
        request = _make_request({
            "username": "emp-001",
            "password": "bad.token",
            "vhost": "/",
        })
        response = await mqtt_auth_user(request)

    assert response.text == "deny"


@pytest.mark.asyncio
async def test_mqtt_auth_vhost_valid_vhost():
    """Valid vhost with authenticated user returns 'allow'."""
    fake_payload = {"sub": "emp-001", "employee_id": "emp-001"}

    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=fake_payload)):
        request = _make_request({
            "username": "emp-001",
            "password": "valid.jwt",
            "vhost": "/",
        })
        response = await mqtt_auth_vhost(request)

    assert response.text == "allow"


@pytest.mark.asyncio
async def test_mqtt_auth_resource_authenticated():
    """Authenticated employee is allowed to access resources."""
    fake_payload = {"sub": "emp-001", "employee_id": "emp-001"}

    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=fake_payload)):
        request = _make_request({
            "username": "emp-001",
            "password": "valid.jwt",
            "resource": "exchange",
            "name": "amq.topic",
            "permission": "write",
        })
        response = await mqtt_auth_resource(request)

    assert response.text == "allow"


@pytest.mark.asyncio
async def test_mqtt_auth_topic_own_employee():
    """Employee can publish/subscribe to their own topic namespace (dot form)."""
    fake_payload = {"sub": "emp-123", "employee_id": "emp-123"}

    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=fake_payload)):
        with patch.object(mqtt_auth_mod, "extract_employee_id", return_value="emp-123"):
            with patch.object(mqtt_auth_mod, "has_admin_scope", return_value=False):
                request = _make_request({
                    "username": "emp-123",
                    "password": "valid.jwt",
                    "routing_key": "employees.emp-123.location",
                    "permission": "write",
                })
                response = await mqtt_auth_topic(request)

    assert response.text == "allow"


@pytest.mark.asyncio
async def test_mqtt_auth_topic_other_employee():
    """Employee cannot publish to another employee's topic namespace."""
    fake_payload = {"sub": "emp-123", "employee_id": "emp-123"}

    with patch.object(mqtt_auth_mod, "decode_mqtt_token", new=AsyncMock(return_value=fake_payload)):
        with patch.object(mqtt_auth_mod, "extract_employee_id", return_value="emp-123"):
            with patch.object(mqtt_auth_mod, "has_admin_scope", return_value=False):
                request = _make_request({
                    "username": "emp-123",
                    "password": "valid.jwt",
                    "routing_key": "employees.emp-999.location",
                    "permission": "write",
                })
                response = await mqtt_auth_topic(request)

    assert response.text == "deny"
