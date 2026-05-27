# TASK-036: FCM Push Provider + HMAC Webhook Helpers

**Feature**: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
**Spec**: `sdd/specs/mqtt-rabbitmq-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-033
**Assigned-to**: unassigned

---

## Context

Two of the dispatcher's five fan-out channels: FCM HTTP v1 push and HMAC-SHA256-signed
outbound webhooks. APNs is explicitly out of v1 — iOS reached via FCM's APNs bridge.

Implements **Spec Module 8**: Push Providers & Webhooks Helpers.

---

## Scope

Create:

- `navigator/ext/geofencing/push_providers/__init__.py` defining `PushProvider` ABC:
  ```python
  class PushProvider(ABC):
      @abstractmethod
      async def send(self, device_token: str, payload: dict) -> None: ...
  ```
- `navigator/ext/geofencing/push_providers/fcm.py` with
  `FCMProvider(PushProvider)`:
  - `__init__(self, service_account_path: str, project_id: str, session:
    aiohttp.ClientSession | None = None)`.
  - Loads the service-account JSON; caches the **service-account JWT** access
    token (1 hour TTL); refreshes when within 60s of expiry.
  - `async send(self, device_token, payload)` POSTs to
    `https://fcm.googleapis.com/v1/projects/{project_id}/messages:send` with
    body `{"message": {"token": device_token, "data": payload, ...}}` and bearer
    `Authorization`. Raises a structured `FCMError` on non-2xx with the FCM
    error code; the dispatcher catches per-channel and logs.
  - JWT signing uses the already-transitive `PyJWT`.
  - **Do NOT** add an SDK (`firebase-admin` etc.) — straight HTTP via `aiohttp`.
- `navigator/ext/geofencing/webhooks.py`:
  - `def sign_payload(body: bytes, secret: bytes, *, algorithm: str =
    WEBHOOK_SIGNING_ALGORITHM) -> str` — returns hex digest (no `sha256=`
    prefix; the caller adds it to the header value).
  - `async dispatch_webhook(webhook: Webhook, body: dict, *,
    session: aiohttp.ClientSession, decrypt: Callable[[bytes], bytes],
    retries: int = 3) -> None`:
    - `decrypt(webhook.secret_encrypted)` produces the raw secret bytes.
    - Canonical JSON body via `json.dumps(body, separators=(",",":"),
      sort_keys=True).encode("utf-8")`.
    - Headers: `X-Navigator-Signature: sha256=<hex>`,
      `X-Navigator-Timestamp: <unix>`, `Content-Type: application/json`.
    - Retry on `aiohttp.ClientError` or non-2xx with exponential backoff
      (`1s, 2s, 4s`). After exhausting retries, log ERROR and drop (no DLQ in v1).
- **`decrypt` is injected** — TASK-038 (CRUD) wires it from `navigator_auth`
  secret-storage primitives. Do NOT hardcode the decrypt impl here.

**NOT in scope**: dispatcher composition, CRUD endpoints, APNs (deferred to v2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/ext/geofencing/push_providers/__init__.py` | CREATE | `PushProvider` ABC |
| `navigator/ext/geofencing/push_providers/fcm.py` | CREATE | `FCMProvider` |
| `navigator/ext/geofencing/webhooks.py` | CREATE | `sign_payload`, `dispatch_webhook` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio, hmac, hashlib, json, time, logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Optional
import aiohttp                       # already a project dep
import jwt                           # PyJWT, transitive via navigator_auth
from navigator.conf import WEBHOOK_SIGNING_ALGORITHM
from navigator.ext.geofencing.models import Webhook
```

### Existing Signatures to Use

```python
# navigator/ext/geofencing/models.py (from TASK-033)
@dataclass(slots=True)
class Webhook:
    id: int; tenant_id: str; url: str
    secret_encrypted: bytes
    geofence_filter: Optional[int]; active: bool
```

### Does NOT Exist

- ~~`aioapns` / `apns2`~~ — explicitly NOT added in v1; do not import.
- ~~`firebase-admin` SDK~~ — do not import; use raw `aiohttp` + service-account
  JWT.
- ~~A canonical Navigator HMAC util~~ — implement inline. The crypto is one
  `hmac.new(secret, body, hashlib.sha256).hexdigest()` call.
- ~~A built-in webhook retry queue~~ — in-process exponential backoff is the v1
  contract; v2 may add persistence.
- ~~Webhook secret decryption helpers in this module~~ — `decrypt` is injected
  from TASK-038/039 wiring against `navigator_auth` primitives.

### Important Non-Obvious Facts

- FCM HTTP v1 service-account JWT scope: `https://www.googleapis.com/auth/firebase.messaging`.
- The FCM JWT exchange (sign service-account JWT → exchange at
  `https://oauth2.googleapis.com/token` for an OAuth2 access token) is what the
  provider caches. The access token is what goes on `Authorization: Bearer ...`,
  NOT the service-account JWT.
- HMAC signature is **stable across implementations** when both sides agree on
  the canonical-JSON encoding. Use `separators=(",",":")` + `sort_keys=True` so
  recipients can recompute deterministically.

---

## Acceptance Criteria

- [ ] `sign_payload(b"...", b"secret")` is deterministic and matches
      `hmac.new(secret, body, sha256).hexdigest()`.
- [ ] `dispatch_webhook` sends the body with `X-Navigator-Signature` and
      `X-Navigator-Timestamp` headers and bumps a counter on retry.
- [ ] On retries exhausted: log ERROR, drop silently (no exception leaks to the
      caller).
- [ ] `FCMProvider.send(...)` POSTs to the documented FCM HTTP v1 endpoint with a
      bearer token; raises `FCMError` on non-2xx.
- [ ] Service-account access token is cached and refreshed within 60s of expiry.
- [ ] No `aioapns` / `firebase-admin` / `apns2` imports anywhere.
- [ ] `decrypt` is a constructor/parameter injection — webhooks.py never calls a
      hardcoded decrypt function.

---

## Agent Instructions

1. `source .venv/bin/activate`.
2. Implement the three modules.
3. Smoke-import: `python -c "from navigator.ext.geofencing.webhooks import
   sign_payload; print(sign_payload(b'x', b'k'))"`.
4. Tests deferred to TASK-041.
5. Update index; move file on completion.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
