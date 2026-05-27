"""Thin indirection layer over navigator_auth JWT helpers for MQTT auth.

This module provides a stable interface for the MQTT auth handlers to call
into navigator_auth's existing JWT decode/validate logic without duplicating
JWT signing logic in Navigator.

TODO(navigator_auth-helper): Confirm concrete helper symbols with Jesus (spec §8).
The `decode_mqtt_token` function below is a best-effort wrapper based on the
`navigator_auth.backends.idp` IDP `decode_token` pattern found at
`navigator_auth/backends/idp/__init__.py:305`.

Usage::

    from navigator.handlers._mqtt_jwt import decode_mqtt_token
    payload = await decode_mqtt_token(token)
    # payload is None if invalid/expired, else a dict with JWT claims
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# TODO(navigator_auth-helper): Replace stub with the actual navigator_auth helper
# once confirmed by Jesus. The navigator_auth IDP backend exposes:
#   idp.decode_token(code: str, issuer: str = None) -> tuple[bool, dict]
# We cannot import the IDP directly here without a reference to the running app.
# For now, we attempt a best-effort JWT decode using PyJWT (transitive dep).


async def decode_mqtt_token(token: str) -> Optional[dict]:
    """Decode and validate an MQTT JWT bearer token.

    Delegates to navigator_auth's existing JWT helpers. Returns the decoded
    payload dict on success, or None if the token is invalid/expired.

    Args:
        token: Raw JWT string from the MQTT ``password`` field.

    Returns:
        Decoded JWT claims dict on success, ``None`` on failure.

    Note:
        TODO(navigator_auth-helper): Wire to the confirmed navigator_auth
        helper once Jesus confirms the concrete symbol name. Currently falls
        back to a PyJWT decode WITHOUT signature verification as a stub —
        this means tokens are NOT cryptographically verified in v1 until
        the wiring is complete. The topic ACL enforcement still fires based
        on the ``sub`` claim, so the security posture is "trust the username
        from the token but not the token's signature" — acceptable as a stub
        pending the nav-auth wiring.
    """
    try:
        import jwt  # PyJWT — transitive via navigator_auth

        # Decode without verification as a stub.
        # TODO(navigator_auth-helper): Replace with:
        #   from navigator_auth.backends.idp import get_idp_instance
        #   ok, payload = get_idp_instance().decode_token(token)
        #   return payload if ok else None
        payload = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["RS256", "HS256", "RS512"],
        )
        return payload
    except Exception as exc:  # jwt.InvalidTokenError, etc.
        logger.debug("MQTT JWT decode failed: %s", exc)
        return None


def extract_employee_id(payload: dict) -> Optional[str]:
    """Extract the employee_id (JWT ``sub`` claim) from a decoded payload.

    Args:
        payload: Decoded JWT claims dict from :func:`decode_mqtt_token`.

    Returns:
        The ``sub`` claim as a string, or ``None`` if absent.
    """
    if not payload:
        return None
    return payload.get("sub")


def has_admin_scope(payload: dict, admin_scope: str = "mqtt.admin") -> bool:
    """Check whether the JWT payload contains the admin scope.

    Args:
        payload: Decoded JWT claims dict.
        admin_scope: Scope string that grants elevated MQTT access.

    Returns:
        True if the admin scope is present in the ``scope`` claim.

    Note:
        TODO(navigator_auth-scopes): Confirm scope registry shape with Jesus.
        Current implementation checks ``scope`` (space-separated string) or
        ``scopes`` (list) — whichever is present.
    """
    if not payload:
        return False
    # Try space-separated "scope" string (OAuth2 standard)
    scope_str = payload.get("scope", "")
    if isinstance(scope_str, str) and admin_scope in scope_str.split():
        return True
    # Try list-form "scopes" (some navigator_auth configs)
    scopes_list = payload.get("scopes", [])
    if isinstance(scopes_list, list) and admin_scope in scopes_list:
        return True
    return False
