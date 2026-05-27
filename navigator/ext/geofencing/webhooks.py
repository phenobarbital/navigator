"""HMAC-SHA256 Webhook Dispatch Helpers.

Provides two public functions:

- :func:`sign_payload` — compute a deterministic HMAC-SHA256 hex digest.
- :func:`dispatch_webhook` — POST a signed payload to a webhook URL with
  exponential-backoff retry.

The HMAC secret is injected as a ``decrypt`` callable so this module never
handles raw secrets or hardcodes an encryption scheme.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 8.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from typing import Optional

import aiohttp

from navigator.conf import WEBHOOK_SIGNING_ALGORITHM
from navigator.ext.geofencing.models import Webhook

logger = logging.getLogger(__name__)


def sign_payload(
    body: bytes,
    secret: bytes,
    *,
    algorithm: str = WEBHOOK_SIGNING_ALGORITHM,
) -> str:
    """Compute a deterministic HMAC hex digest over ``body``.

    The digest is suitable for use in the ``X-Navigator-Signature`` header
    as ``sha256=<hex>``.

    Args:
        body: Canonical JSON bytes (use
            ``json.dumps(data, separators=(",",":"), sort_keys=True).encode()``).
        secret: Raw HMAC signing key bytes.
        algorithm: Hash algorithm name (default ``"sha256"``).

    Returns:
        Lowercase hex digest string (no prefix — callers prepend ``sha256=``).

    Example::

        digest = sign_payload(b'{"a":1}', b"my-secret")
        header = f"sha256={digest}"
    """
    hash_fn = getattr(hashlib, algorithm, None)
    if hash_fn is None:
        raise ValueError(f"Unsupported HMAC algorithm: {algorithm!r}")
    mac = hmac.new(secret, body, hash_fn)
    return mac.hexdigest()


def _canonical_json(data: dict) -> bytes:
    """Produce deterministic, compact JSON bytes from a dict.

    Args:
        data: JSON-serializable dict.

    Returns:
        UTF-8 encoded bytes with ``separators=(",",":")`` and
        ``sort_keys=True`` for reproducible HMAC computation.
    """
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def dispatch_webhook(
    webhook: Webhook,
    body: dict,
    *,
    session: aiohttp.ClientSession,
    decrypt: Callable[[bytes], bytes],
    retries: int = 3,
) -> None:
    """POST a signed payload to a webhook URL with exponential-backoff retry.

    Computes the canonical JSON body, signs it with the decrypted HMAC
    secret, and POSTs to ``webhook.url`` with:

    - ``X-Navigator-Signature: sha256=<hex>``
    - ``X-Navigator-Timestamp: <unix_seconds>``
    - ``Content-Type: application/json``

    On ``aiohttp.ClientError`` or non-2xx response, retries with
    exponential backoff (1s, 2s, 4s).  After all retries are exhausted,
    logs ERROR and drops the event (no persistence in v1).

    Args:
        webhook: :class:`~navigator.ext.geofencing.models.Webhook` row with
            ``url`` and ``secret_encrypted``.
        body: JSON-serializable dict to POST.
        session: ``aiohttp.ClientSession`` for outbound HTTP.
        decrypt: Callable that decrypts ``webhook.secret_encrypted`` and
            returns the raw secret bytes.
        retries: Number of attempts (default 3; delays: 1s, 2s, 4s).
    """
    secret: bytes = decrypt(webhook.secret_encrypted)
    canonical_body: bytes = _canonical_json(body)
    hex_digest = sign_payload(canonical_body, secret)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Navigator-Signature": f"sha256={hex_digest}",
        "X-Navigator-Timestamp": timestamp,
    }

    delay = 1.0
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            async with session.post(
                webhook.url, data=canonical_body, headers=headers
            ) as resp:
                if 200 <= resp.status < 300:
                    logger.debug(
                        "dispatch_webhook: success url=%s status=%d attempt=%d",
                        webhook.url,
                        resp.status,
                        attempt,
                    )
                    return
                body_text = await resp.text()
                last_exc = Exception(
                    f"HTTP {resp.status} from {webhook.url}: {body_text[:200]}"
                )
                logger.warning(
                    "dispatch_webhook: non-2xx url=%s status=%d attempt=%d/%d",
                    webhook.url,
                    resp.status,
                    attempt,
                    retries,
                )
        except aiohttp.ClientError as exc:
            last_exc = exc
            logger.warning(
                "dispatch_webhook: client error url=%s attempt=%d/%d: %s",
                webhook.url,
                attempt,
                retries,
                exc,
            )

        if attempt < retries:
            await asyncio.sleep(delay)
            delay *= 2  # exponential: 1s, 2s, 4s

    logger.error(
        "dispatch_webhook: exhausted %d retries for url=%s — dropping: %s",
        retries,
        webhook.url,
        last_exc,
    )
