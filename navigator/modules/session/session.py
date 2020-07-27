from aiohttp.web import middleware
from typing import Any
from aiohttp import web
import json

class AbstractSession(object):
    _backend = None

    @property
    def Backend(self, backend: Any = None):
        self._backend = backend

    async def decode(self, key):
        pass

    async def decode(self, key):
        pass
