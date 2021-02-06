"""Session System for Navigator Auth backend."""
import asyncio
import rapidjson
import base64
from cryptography import fernet
import time
from abc import ABC, abstractmethod
from functools import wraps
# redis pool
import aioredis
# memcached
import aiomcache
from functools import partial
# aiohttp session
from aiohttp_session import get_session, new_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_session.redis_storage import RedisStorage
from aiohttp_session.memcached_storage import MemcachedStorage
from navigator.conf import (
    SESSION_URL,
    MEMCACHE_HOST,
    MEMCACHE_PORT
)

class AbstractSession(ABC):
    """Abstract Base Session."""
    session = None
    session_name: str = 'AIOHTTP_SESSION'
    secret_key: str = None

    def __init__(self, secret: str = '', name: str = '', **kwargs):
        if name:
            self.session_name = name
        if not secret:
            fernet_key = fernet.Fernet.generate_key()
            self.secret_key = base64.urlsafe_b64decode(fernet_key)
        else:
            self.secret_key = secret

    @abstractmethod
    async def configure(self):
        pass

    async def create_session(self, request, **kwargs):
        app = request.app
        try:
            session = await new_session(request)
        except Exception as err:
            print(err)
            return False
        last_visit = session["last_visit"] if "last_visit" in session else "Never"
        session["last_visit"] = time.time()
        session["last_visited"] = "Last visited: {}".format(last_visit)
        # think about saving user data on session when create
        if 'user' in kwargs:
            user = kwargs['user']
            app["user"] = user
            request.user = user
            session["user"] = user
        app["session"] = session
        return True

    async def forgot_session(self, request):
        session = await get_session(request)
        session.invalidate()
        app = request.app
        try:
            app["user"] = None
            request.user = None
        except Exception as err:
            print(err)
        app["session"] = None


class CookieSession(AbstractSession):
    """Encrypted Cookie Session Storage."""

    def configure(self):
        self.session = EncryptedCookieStorage(
            self.secret_key,
            cookie_name=self.session_name
        )
        return self.session


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
                self.session = RedisStorage(
                    self._pool,
                    cookie_name=self.session_name,
                    encoder=rapidjson.dumps,
                    decoder=rapidjson.loads
                )
                return self.session
            except Exception as err:
                print(err)
                return False
        return asyncio.get_event_loop().run_until_complete(
            _make_redis()
        )


class MemcacheSession(AbstractSession):
    """Session Storage based on Memcache."""
    _pool = None

    async def get_mcache(self, **kwargs):
        loop = asyncio.get_event_loop()
        return aiomcache.Client(MEMCACHE_HOST, MEMCACHE_PORT, loop=loop)

    def configure(self, **kwargs):
        #jsondumps = partial(json.dumps, cls=cls)
        async def _make_mcache():
            try:
                self._pool = await self.get_mcache()
                self.session = MemcachedStorage(
                    self._pool,
                    cookie_name=self.session_name,
                    encoder=rapidjson.dumps,
                    decoder=rapidjson.loads
                )
                return self.session
            except Exception as err:
                print(err)
                return False
        return asyncio.get_event_loop().run_until_complete(
            _make_mcache()
        )
