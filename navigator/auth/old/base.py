""" Abstract Class for create Session Objects."""
import time
import asyncio
import logging
import base64
from cryptography import fernet
from abc import abstractmethod
from .abstract import AbstractSession
# aiohttp session
from aiohttp_session import get_session, new_session
from navigator.auth.models import User
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
)


class BaseSession(AbstractSession):
    """Base Session from all Session-based session."""

    @abstractmethod
    async def configure_session(self, app):
        pass

    async def get_session(self, request):
        session = await get_session(request)
        return session

    async def create(self, request, userdata: dict = {}):
        app = request.app
        try:
            session = await new_session(request)
        except Exception as err:
            logging.error(f'Error creating Session: {err}')
            return False
        last_visit = session["last_visit"] if "last_visit" in session else None
        session["last_visit"] = time.time()
        session["last_visited"] = "Last visited: {}".format(last_visit)
        if userdata:
            for key,data in userdata.items():
                session[key] = data
        request["session"] = session
        request['User'] = userdata
        try:
            request[self.user_property] = userdata[self.user_property]
        except KeyError:
            pass
        return session

    async def invalidate(self, session):
        try:
            session.invalidate()
        except Exception as err:
            print(err)
            logging.error(err)
