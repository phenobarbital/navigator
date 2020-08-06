# -*- coding: utf-8 -*-
#!/usr/bin/env python3

import os
import sys

import asyncio
import json
import base64
from navigator.modules.session.session import AbstractSession
from navigator.conf import config, asyncpg_url, DEBUG, SESSION_URL, SESSION_PREFIX
from navigator.handlers import nav_exception_handler
from asyncdb import AsyncPool

"""
navSession
   Basic Interaction with Session backend of Django
"""

class navSession(object):
    _loop = None
    _redis = None
    _cache = None
    _result = {}
    _session = None

    def __init__(self, dsn='', loop=None, session: AbstractSession=None):
        self._loop = loop
        self._result = {}
        self._session_key = ''
        self._session_id = None
        self._loop.set_exception_handler(nav_exception_handler)
        #set the connector to redis pool
        #TODO: define other session backend
        self._redis = redis = AsyncPool('redis', dsn=dsn, loop=self._loop)
        self._session = session

    def cache(self):
        return self._cache

    def set_result(self, result):
        self._result = result

    async def connect(self):
        await self._redis.connect()
        if self._redis:
            self._cache = await self._redis.acquire()
            self._session.Backend(self)

    async def close(self):
        if self._cache:
            await self._cache.close()
        await self._redis.close()
        #self._loop.close()

    async def decode(self, key):
        return await self._session.decode(key)

    async def encode(self, key, data):
        return await self._session.encode(key, data)

    def session_key(self):
        return self._session_key

    def session_id(self):
        return self._session_id

    def content(self):
        return self._result

    async def get(self, key):
        if not self._result:
            await self.decode()
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
