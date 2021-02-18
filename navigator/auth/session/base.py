""" Abstract Class for create Session Objects."""
import time
import asyncio
import logging
import base64
from functools import wraps, partial
from cryptography import fernet
from abc import ABC, abstractmethod
# aiohttp session
from aiohttp_session import get_session, new_session
from navigator.auth.models import User
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT
)

class AbstractSession(ABC):
    """Abstract Base Session."""
    session = None
    _session_obj = None
    session_name: str = 'AIOHTTP_SESSION'
    secret_key: str = None
    user_property: str = 'user'
    user_attribute: str = 'user_id'
    username_attribute: str = 'username'
    user_mapping: dict = {'user_id': 'id','username': 'username'}

    def __init__(
            self,
            secret: str = '',
            name: str = '',
            user_property: str = 'user',
            user_attribute: str = 'user_id',
            username_attribute: str = 'username',
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

    @abstractmethod
    async def configure(self):
        pass

    def get_session(self):
        return self._session_obj

    async def create_session(self, request, user, userdata):
        app = request.app
        session = None
        try:
            self._session_obj = await new_session(request)
        except Exception as err:
            print(err)
            return False
        last_visit = self._session_obj["last_visit"] if "last_visit" in self._session_obj else "Never"
        self._session_obj["last_visit"] = time.time()
        self._session_obj["last_visited"] = "Last visited: {}".format(last_visit)
        # think about saving user data on session when create
        app['User'] = user
        app[self.user_property] = userdata
        self._session_obj[self.user_property] = userdata
        app["session"] = self.session
        return session

    async def forgot_session(self, request):
        app = request.app
        session = await get_session(request)
        session.invalidate()
        try:
            app['User'] = None
            app[self.user_property] = None
            request.user = None
        except Exception as err:
            print(err)
        app["session"] = None
        self._session_obj = None
