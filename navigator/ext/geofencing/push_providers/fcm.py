"""FCM Push Provider — Firebase Cloud Messaging HTTP v1.

Implements :class:`~navigator.ext.geofencing.push_providers.PushProvider`
using the FCM HTTP v1 API.  No Firebase Admin SDK is used — authentication
is done via a service-account JWT signed with ``PyJWT`` (transitive dep).

The FCM access token is cached with a one-hour TTL and refreshed within
60 seconds of expiry.

iOS support is provided via FCM's APNs bridge.  Native APNs (``aioapns``)
is deferred to v2.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 8.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import aiohttp
import jwt  # PyJWT — transitive via navigator_auth

from navigator.ext.geofencing.push_providers import PushProvider

logger = logging.getLogger(__name__)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


class FCMError(Exception):
    """Raised when the FCM HTTP v1 API returns a non-2xx response.

    Attributes:
        status: HTTP status code.
        body: Response body text.
    """

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"FCM error {status}: {body}")
        self.status = status
        self.body = body


class FCMProvider(PushProvider):
    """Firebase Cloud Messaging HTTP v1 push provider.

    Loads a service-account JSON key file, builds signed JWTs, exchanges
    them for OAuth2 access tokens at the Google token endpoint, and POSTs
    to the FCM HTTP v1 send endpoint.

    Args:
        service_account_path: Path to the service-account JSON key file.
        project_id: GCP project ID (used in the FCM API URL).
        session: Optional ``aiohttp.ClientSession``.  If ``None``, a new
            session is created on the first :meth:`send` call.

    Example::

        provider = FCMProvider(
            service_account_path="/run/secrets/fcm_service_account.json",
            project_id="my-gcp-project",
        )
        await provider.send(device_token, {"kind": "enter", "geofence_id": 42})
    """

    def __init__(
        self,
        service_account_path: str,
        project_id: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialize FCMProvider.

        Args:
            service_account_path: Path to the service-account JSON key file.
            project_id: GCP project ID used in the FCM send URL.
            session: Optional shared aiohttp client session.
        """
        self._project_id = project_id
        self._session = session
        self._owns_session = session is None

        # Load service account credentials
        with open(service_account_path, "r", encoding="utf-8") as fh:
            self._service_account: dict = json.load(fh)

        # Token cache
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        self.logger = logging.getLogger(self.__class__.__name__)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the aiohttp session, creating one if needed.

        Returns:
            An :class:`aiohttp.ClientSession` instance.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    def _build_sa_jwt(self) -> str:
        """Build a signed service-account JWT for the FCM OAuth2 exchange.

        Returns:
            A signed JWT string using RS256 with the service-account private key.
        """
        now = int(time.time())
        payload = {
            "iss": self._service_account["client_email"],
            "scope": _FCM_SCOPE,
            "aud": _OAUTH_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        private_key = self._service_account["private_key"]
        return jwt.encode(payload, private_key, algorithm="RS256")

    async def _refresh_access_token(self) -> None:
        """Exchange the service-account JWT for a short-lived OAuth2 access token.

        Caches the resulting access token until 60 seconds before expiry.
        """
        sa_jwt = self._build_sa_jwt()
        session = await self._ensure_session()
        async with session.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": sa_jwt,
            },
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise FCMError(resp.status, f"OAuth2 token exchange failed: {body}")
            data = await resp.json()
            self._access_token = data["access_token"]
            # expires_in is in seconds; cache with 60s safety margin
            expires_in = int(data.get("expires_in", 3600))
            self._token_expires_at = time.time() + expires_in - 60
        self.logger.debug("FCMProvider: access token refreshed")

    async def _get_access_token(self) -> str:
        """Return a valid OAuth2 access token, refreshing if necessary.

        Returns:
            Valid Bearer access token string.
        """
        if self._access_token is None or time.time() >= self._token_expires_at:
            await self._refresh_access_token()
        return self._access_token  # type: ignore[return-value]

    async def send(self, device_token: str, payload: dict) -> None:
        """Send a push notification via FCM HTTP v1.

        Args:
            device_token: FCM registration token for the target device.
                iOS devices are reached via FCM's APNs bridge.
            payload: JSON-serializable data dict to include in the FCM
                ``data`` field.

        Raises:
            FCMError: If FCM returns a non-2xx response.
        """
        access_token = await self._get_access_token()
        session = await self._ensure_session()
        url = _FCM_SEND_URL.format(project_id=self._project_id)
        body = {
            "message": {
                "token": device_token,
                "data": {k: str(v) for k, v in payload.items()},
            }
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status < 200 or resp.status >= 300:
                body_text = await resp.text()
                raise FCMError(resp.status, body_text)
        self.logger.debug(
            "FCMProvider: notification sent to device %s...", device_token[:8]
        )

    async def aclose(self) -> None:
        """Close the underlying aiohttp session if we own it.

        Should be called during application shutdown.
        """
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
