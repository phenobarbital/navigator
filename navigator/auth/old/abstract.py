""" Abstract Class for create Session Objects."""
import asyncio
import logging
import base64
from functools import wraps, partial
from cryptography import fernet
from abc import ABC, abstractmethod

# aiohttp session
from navigator.auth.models import User
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
)


class AbstractSession(ABC):
    """Abstract Base Session."""

    session = None
    session_name: str = "NAVIGATOR_SESSION"
    secret_key: str = None
    user_property: str = "user"
    user_attribute: str = "user_id"
    username_attribute: str = "username"

    def __init__(
        self,
        secret: str = "",
        name: str = "",
        user_property: str = "user",
        user_attribute: str = "user_id",
        username_attribute: str = "username",
        **kwargs
    ):
        if name:
            self.session_name = name
        else:
            self.session_name = SESSION_NAME
        if not secret:
            fernet_key = fernet.Fernet.generate_key()
            self.secret_key = base64.urlsafe_b64decode(fernet_key)
        else:
            self.secret_key = secret
        # user property:
        self.user_property = user_property
        self.user_attribute = user_attribute
        self.username_attribute = username_attribute
        # Session Object
        self.session = None

    @abstractmethod
    async def configure_session(self, app):
        pass

    @abstractmethod
    async def get_session(self, request):
        pass

    @abstractmethod
    async def create(self, request, userdata):
        pass

    @abstractmethod
    async def invalidate(self, session):
        pass

    async def forgot(self, request):
        app = request.app
        session = await self.get_session(request)
        await self.invalidate(session)
        try:
            request["User"] = None
            request[self.user_property] = None
            request.user = None
            del request[self.user_property]
        except Exception as err:
            print(err)
        request["session"] = None
