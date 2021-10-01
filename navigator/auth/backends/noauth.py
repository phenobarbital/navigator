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
         Description: No-Authentication for Anonymous connections.
        """
        async def middleware(request):
            jwt_token = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                # Authorization Exception
                return await authz
            try:
                jwt_token = self.decode_token(request)
                # load session information
                session = await get_session(request, jwt_token)
            except NavException as err:
                response = {
                    "message": "Token Error",
                    "error": err.message,
                    "status": err.state,
                }
                return web.json_response(response, status=err.state)
            except Exception as err:
                raise web.HTTPBadRequest(reason=f"Bad Request: {err!s}")
            if not jwt_token and AUTH_CREDENTIALS_REQUIRED is True:
                raise web.HTTPUnauthorized(
                    reason="User not Authorized"
                )
            else:
                # processing the token and recover the user session
                pass
            return await handler(request)

        return middleware
