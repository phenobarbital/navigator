"""Session based on REDIS Server."""
import asyncio
import json
import rapidjson

# redis pool
import aioredis
from functools import wraps, partial
from aiohttp_session.redis_storage import RedisStorage
from aiohttp_session import setup as setup_session
from .base import AbstractSession
from navigator.conf import DOMAIN, SESSION_URL, SESSION_TIMEOUT


class RedisSession(AbstractSession):
    """Session Storage based on Redis."""

    _pool = None

    async def setup_redis(self, app):
        redis = aioredis.ConnectionPool.from_url(
                SESSION_URL,
                decode_responses=True,
                encoding='utf-8'
        )
        async def close_redis(app):
            await redis.disconnect(inuse_connections = True)
        app.on_cleanup.append(close_redis)
        return redis

    def configure_session(self, app, **kwargs):
        async def _make_mredis():
            _encoder = partial(rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601)
            try:
                self._pool = await self.setup_redis(app)
                setup_session(
                    app,
                    RedisStorage(
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

        return asyncio.get_event_loop().run_until_complete(_make_mredis())
