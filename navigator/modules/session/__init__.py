# -*- coding: utf-8 -*-
#!/usr/bin/env python3

import asyncio
import base64
import json
import os
import sys

from aiohttp import web
from asyncdb import AsyncDB

from navigator.conf import DEBUG, SESSION_PREFIX, SESSION_URL, config
from navigator.handlers import nav_exception_handler
from navigator.modules.session.session import AbstractSession
from navigator.views import BaseView


class UserSession(BaseView):
    async def get(self):
        try:
            session = self.request["session"]
        except KeyError:
            session = None
        try:
            if not session:
                headers = {"x-status": "Empty", "x-message": "Invalid User Session"}
                return self.no_content(headers=headers)
            else:
                headers = {"x-status": "OK", "x-message": "Session OK"}
                data = session.content()
                if data:
                    return self.json_response(response=data, headers=headers)
        except Exception as err:
            return self.error(request, exception=err)


class navSession(object):
    """
    navSession
       Basic Interaction with Session backend of Django
    """

    _loop = None
    _redis = None
    _cache = None
    _result = {}
    _session = None

    def __init__(self, dsn="", session: AbstractSession = None, loop=None):
        if loop:
            self._loop = loop
        else:
            self._loop = asyncio.get_event_loop()
        self._result = {}
        self._session_key = ""
        self._session_id = None
        self._loop.set_exception_handler(nav_exception_handler)
        # TODO: define other session backend
        self._cache = redis = AsyncDB("redis", dsn=dsn)
        self._session = session

    def cache(self):
        return self._cache

    def set_result(self, result):
        self._result = result

    async def connect(self):
        await self._cache.connection()
        if self._cache:
            self._session.Backend(self)

    async def close(self):
        if self._cache:
            await self._cache.close()
            await self._cache.wait_closed()

    async def logout(self):
        """
        logout.
           Clear all session info
        """
        self._session_id = None
        self._session_key = None
        self._result = {}

    async def decode(self, key):
        return await self._session.decode(key)

    async def encode(self, key, data):
        return await self._session.encode(key, data)

    def session_key(self):
        return self._session_key

    def session_id(self):
        return self._session_id

    def id(self, id):
        self._session_id = id

    def content(self):
        return self._result

    async def get(self, key):
        if key in self._result:
            return self._result[key]
        else:
            return None

    async def set(self, key, value):
        self._result[key] = value

    async def add(self, **kwargs):
        self._result = {**self._result, **kwargs}

    """
    Magic Methods
    """

    def __getitem__(self, key):
        """
        Sequence-like operators
        """
        if self._result:
            return self._result[key]
        else:
            return False

    def __contains__(self, key):
        if key in self._result:
            return True
        else:
            return False

    def __iter__(self):
        return iter(self._result)

    def __getattr__(self, key):
        if self._result:
            return self._result[key]
        else:
            raise KeyError("Invalid Session")
