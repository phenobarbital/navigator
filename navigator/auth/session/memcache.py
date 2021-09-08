"""Memcached-based Session Object."""
import asyncio
import rapidjson
from functools import wraps, partial

# memcached
import aiomcache
from aiohttp_session.memcached_storage import MemcachedStorage
from aiohttp_session import setup as setup_session
from .base import AbstractSession
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_TIMEOUT,
    MEMCACHE_HOST,
    MEMCACHE_PORT,
)


class MemcacheSession(AbstractSession):
    """Session Storage based on Memcache."""

    _pool = None

    async def get_mcache(self, **kwargs):
        loop = asyncio.get_event_loop()
        return aiomcache.Client(MEMCACHE_HOST, MEMCACHE_PORT, loop=loop)

    def configure_session(self, app, **kwargs):
        async def _make_mcache():
            _encoder = partial(rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601)
            try:
                self._pool = await self.get_mcache()
                setup_session(
                    app,
                    MemcachedStorage(
                        self._pool,
                        cookie_name=self.session_name,
                        encoder=_encoder,
                        decoder=rapidjson.loads,
                        max_age=int(SESSION_TIMEOUT),
                    ),
                )
            except Exception as err:
                print(err)
                return False

        return asyncio.get_event_loop().run_until_complete(_make_mcache())
