"""Unit tests for Geofence + Webhook CRUD handlers.

Coverage:
- test_crud_tenant_scoped_list: tenant A can only see its own geofences
- test_crud_invalid_polygon_rejected: self-intersecting polygon returns 422
- test_crud_webhook_secret_encrypted: secret is encrypted at write time
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from navigator.ext.geofencing.crud import _GeofencingCRUD, register_geofencing_crud_routes


# ---------------------------------------------------------------------------
# Mock DB
# ---------------------------------------------------------------------------


class _MockDB:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._executed = []

    async def fetch_all(self, query, *args):
        if args:
            return [r for r in self._rows if str(r.get("tenant_id")) == str(args[0])]
        return list(self._rows)

    async def fetch_one(self, query, *args):
        rows = await self.fetch_all(query, *args)
        return rows[0] if rows else None

    async def execute(self, query, *args):
        self._executed.append((query, args))


def _make_session(tenant_id="acme", scopes=None):
    """Return a mock session dict."""
    return {"tenant_id": tenant_id, "scopes": scopes or []}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crud_tenant_scoped_list():
    """Tenant A user sees only tenant A geofences."""
    acme_fence = {
        "id": "fence-1",
        "tenant_id": "acme",
        "name": "Office",
        "polygon": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "active": True,
        "dwell_seconds": None,
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
    }
    other_fence = {
        "id": "fence-2",
        "tenant_id": "other",
        "name": "Other Office",
        "polygon": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "active": True,
        "dwell_seconds": None,
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
    }
    db = _MockDB(rows=[acme_fence, other_fence])
    reload_pub = AsyncMock()
    crud = _GeofencingCRUD(db=db, reload_publisher=reload_pub,
                           secret_encrypt=lambda b: b, secret_decrypt=lambda b: b)

    # Mock request with session for tenant "acme"
    request = MagicMock()
    session = _make_session(tenant_id="acme")

    with patch("navigator.ext.geofencing.crud.get_session", return_value=session):
        response = await crud.list_fences(request)

    data = json.loads(response.body)
    assert len(data) == 1
    assert data[0]["tenant_id"] == "acme"


@pytest.mark.asyncio
async def test_crud_invalid_polygon_rejected():
    """POST with self-intersecting polygon returns 422 with reason."""
    db = _MockDB()
    reload_pub = AsyncMock()
    crud = _GeofencingCRUD(db=db, reload_publisher=reload_pub,
                           secret_encrypt=lambda b: b, secret_decrypt=lambda b: b)

    # A bowtie/self-intersecting polygon
    bowtie_wkt = "POLYGON((0 0, 1 1, 0 1, 1 0, 0 0))"
    body = {"name": "bad", "polygon": bowtie_wkt}

    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    session = _make_session()

    with patch("navigator.ext.geofencing.crud.get_session", return_value=session):
        response = await crud.create_fence(request)

    assert response.status == 422
    data = json.loads(response.body)
    assert "reason" in data
    assert data["error"] == "invalid_polygon"


@pytest.mark.asyncio
async def test_crud_webhook_secret_encrypted():
    """Webhook secret is encrypted via secret_encrypt before DB write."""
    db = _MockDB()
    reload_pub = AsyncMock()
    encrypted_secrets = []

    def encrypt(plaintext: bytes) -> bytes:
        result = bytes(b ^ 0xFF for b in plaintext)  # simple XOR for test
        encrypted_secrets.append(result)
        return result

    crud = _GeofencingCRUD(db=db, reload_publisher=reload_pub,
                           secret_encrypt=encrypt, secret_decrypt=lambda b: b)

    body = {"url": "https://example.com/hook", "secret": "my-secret"}
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    session = _make_session()

    with patch("navigator.ext.geofencing.crud.get_session", return_value=session):
        response = await crud.create_webhook(request)

    assert response.status == 201
    # Encrypt was called
    assert len(encrypted_secrets) == 1
    # The stored bytes are NOT the original plaintext
    assert encrypted_secrets[0] != b"my-secret"
    # The response does NOT include the secret
    data = json.loads(response.body)
    assert "secret" not in data
    assert "secret_encrypted" not in data
