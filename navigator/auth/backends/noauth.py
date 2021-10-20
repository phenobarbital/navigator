"""Django Session Backend.

Navigator Authentication using Anonymous Backend
"""
import logging
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthBackend
import uuid
from navigator.conf import AUTH_CREDENTIALS_REQUIRED
from navigator.auth.sessions import get_session
from navigator.exceptions import (
    NavException,
    FailedAuth,
    InvalidAuth
)

class NoAuth(BaseAuthBackend):
    """Basic Handler for No authentication."""

    user_attribute: str = "userid"

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    async def authenticate(self, request):
        key = uuid.uuid4().hex
        payload = {
            self.session_key_property: key,
            self.user_property: None,
            self.username_attribute: "Anonymous"
        }
        token = self.create_jwt(data=payload)
        return {
            "token": token,
            self.session_key_property: key,
            self.username_attribute: "Anonymous"
        }

    async def auth_middleware(self, app, handler):
        """
         NoAuth Middleware.
         Description: Basic Authentication for NoAuth, Basic and Django.
        """
        async def middleware(request):
            jwt_token = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                # Authorization Exception
                return await authz
            try:
                if request['authenticated'] is True:
                    return await handler(request)
            except KeyError:
                pass
            try:
                tenant, jwt_token = self.decode_token(request)
                if jwt_token:
                    # load session information
                    session = await get_session(request, jwt_token, new = False)
                    request['authenticated'] = True
            except NavException as err:
                pass # NoAuth can pass silently when no token was generated
            except Exception as err:
                logging.error(f"Bad Request: {err!s}")
                pass
            return await handler(request)

        return middleware
