"""Session System for Navigator Auth backend."""
import asyncio
import rapidjson
import logging
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
from .models import User
# aiohttp session
from aiohttp_session import get_session, new_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_session.redis_storage import RedisStorage
from aiohttp_session.memcached_storage import MemcachedStorage
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    MEMCACHE_HOST,
    MEMCACHE_PORT,
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

    def __init__(
            self,
            secret: str = '',
            name: str = '',
            user_property: str = 'user',
            user_attribute: str = 'user_id',
            **kwargs
    ):
        if name:
            self.session_name = name
        if not secret:
            fernet_key = fernet.Fernet.generate_key()
            self.secret_key = base64.urlsafe_b64decode(fernet_key)
        else:
            self.secret_key = secret
        # user property:
        self.user_property = user_property
        self.user_attribute = user_attribute

    @abstractmethod
    async def configure(self):
        pass

    def get_session(self):
        return self._session_obj

    async def get_user(self, user) -> User:
        if self.user_attribute in user:
            try:
                u = await User.get(**{"id": user[self.user_attribute]})
                if u:
                    user = {
                        "first_name": u.first_name,
                        "last_name": u.last_name,
                        "email": u.email,
                        "last_login": u.last_login,
                        "username": u.username,
                        "is_superuser": u.is_superuser,
                        "is_staff": u.is_staff,
                        "title": u.title
                    }
                    return [u, user]
            except Exception as err:
                print('ERR ', err)
                logging.error(f'Error getting User {err!s}')
                return None
        else:
            return None

    async def create_session(self, request, **kwargs):
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
        if 'session' in kwargs:
            # dump of session data
            session = kwargs['session']
            self._session_obj['session'] = session
            try:
                user = session[self.user_property]
                app[self.user_property] = user
                self._session_obj[self.user_property] = user
                # getting user:
                try:
                    u, user = await self.get_user(user)
                    app['User'] = u
                    # self._session_obj['User'] = user
                    session['User'] = user
                except Exception as err:
                    print(err)
                    logging.error(err)
            except (KeyError, ValueError) as err:
                logging.error(f'Missing User Information in session: {err!s}')
        # saving session object in App
        app["session"] = self.session
        return session

    async def forgot_session(self, request):
        app = request.app
        session = await get_session(request)
        session.invalidate()
        try:
            app[self.user_property] = None
            request.user = None
        except Exception as err:
            print(err)
        app["session"] = None
        self._session_obj = None


class CookieSession(AbstractSession):
    """Encrypted Cookie Session Storage."""

    def configure(self):
        self.session = EncryptedCookieStorage(
            self.secret_key,
            cookie_name=self.session_name,
            domain=DOMAIN,
            max_age=SESSION_TIMEOUT
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
                    decoder=rapidjson.loads,
                    domain=DOMAIN,
                    max_age=int(SESSION_TIMEOUT)
                )
                return self.session
            except Exception as err:
                print(err)
                return False
        return asyncio.get_event_loop().run_until_complete(
            _make_mcache()
        )
