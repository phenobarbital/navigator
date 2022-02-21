"""Django Session Backend.

Navigator Authentication using Anonymous Backend
"""
import logging
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthBackend
import uuid
from navigator.conf import (
    CREDENTIALS_REQUIRED,
    AUTH_SESSION_OBJECT
)
from navigator.auth.sessions import get_session
from navigator.exceptions import (
    NavException,
    FailedAuth,
    InvalidAuth
)

class NoAuth(BaseAuthBackend):
    """Basic Handler for No authentication."""

    user_attribute: str = "userid"

    def __init__(
        self,
        user_attribute: str = "userid",
        userid_attribute: str = "userid",
        username_attribute: str = "username",
        password_attribute: str = "password",
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        super(NoAuth, self).__init__(
            user_attribute,
            userid_attribute,
            username_attribute,
            password_attribute,
            credentials_required,
            authorization_backends,
            **kwargs
        )

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    def get_userdata(self):
        key = uuid.uuid4().hex
        userdata = {
            AUTH_SESSION_OBJECT: {
                "session": key,
                self.user_property: key,
                self.username_attribute: "Anonymous",
                "first_name": "Anonymous",
                "last_name": "User"
            }
        }
        return [ userdata, key ]

    async def authenticate(self, request):
        userdata, key = self.get_userdata()
        payload = {
            self.session_key_property: key,
            self.user_property: None,
            self.username_attribute: "Anonymous",
            **userdata
        }
        token = self.create_jwt(data=payload)
        return {
            "token": token,
            self.session_key_property: key,
            self.username_attribute: "Anonymous",
            **userdata
        }

    async def auth_middleware(self, app, handler):
        """
         NoAuth Middleware.
         Description: Basic Authentication for NoAuth, Basic, Token and Django.
        """
        async def middleware(request):
            jwt_token = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                # Authorization Exception
                return await authz
            try:
                if request['authenticated'] is True:
                    # already authenticated
                    return await handler(request)
            except KeyError:
                pass
            try:
                tenant, payload = self.decode_token(request)
                if payload:
                    # load session information
                    session = await get_session(request, payload, new = False)
                    request['authenticated'] = True
            except NavException as err:
                pass # NoAuth can pass silently when no token was generated
            except Exception as err:
                logging.error(f"Bad Request: {err!s}")
                pass
            return await handler(request)

        return middleware
