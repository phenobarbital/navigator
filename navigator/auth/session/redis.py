"""Session based on REDIS Server."""
import asyncio
import rapidjson
# redis pool
import aioredis
from functools import wraps, partial
from aiohttp_session.redis_storage import RedisStorage
from .base import AbstractSession
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_TIMEOUT
)


class RedisSession(AbstractSession):
    """Session Storage based on Redis."""
    _pool = None

    async def get_redis(self, **kwargs):
        kwargs['timeout'] = 1
        return await aioredis.create_redis_pool(SESSION_URL, **kwargs)

    def configure(self, **kwargs):
        async def _make_redis():
            try:
                self._pool = await self.get_redis()
                _encoder = partial(rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601)
                self.session = RedisStorage(
                    self._pool,
                    cookie_name=self.session_name,
                    encoder=_encoder,
                    decoder=rapidjson.loads,
                    domain=DOMAIN,
                    max_age=int(SESSION_TIMEOUT)
                )
                return self.session
            except Exception as err:
                print('ERR: ', err)
                return False
        return asyncio.get_event_loop().run_until_complete(
            _make_redis()
        )
