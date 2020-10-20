import json
from typing import Any

from aiohttp import web
from aiohttp.web import middleware


class AbstractSession(object):
    _backend = None
    _parent = None

    def Backend(self, backend: Any = None):
        self._parent = backend
        self._backend = backend.cache()

    async def decode(self, key):
        pass

    async def decode(self, key):
        pass
