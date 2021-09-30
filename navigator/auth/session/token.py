""" Token Session Object."""
import asyncio
import logging
import base64
import aioredis
import rapidjson
import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    Mapping,
    MutableMapping,
    Optional,
    Union
)

from functools import wraps, partial
from .abstract import AbstractSession
from navigator.conf import (
    DOMAIN,
    SESSION_URL,
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
)

class SessionData(MutableMapping[str, Any]):
    """Session dict-like object."""

    _data: Dict[str, Any] = {}
    _db: Callable = None

    def __init__(
        self,
        db: Callable, *,
        data: Optional[Mapping[str, Any]] = {},
        new: bool = False,
        identity: Optional[Any] = None,
        max_age: Optional[int] = None
    ) -> None:
        self._changed = False
        self._data = {}
        self._db = db
        self._identity = data.get('id', None) if data else identity
        self._new = new if data != {} else True
        self._max_age = max_age if max_age else None
        created = data.get('created', None) if data else None
        session_data = data.get('session', None) if data else None
        now = int(time.time())
        age = now - created if created else now
        if max_age is not None and age > max_age:
            session_data = None
        if self._new or created is None:
            self._created = now
        else:
            self._created = created

        if session_data is not None:
            self._data.update(session_data)

    def __repr__(self) -> str:
        return '<{} [new:{}, created:{}] {!r}>'.format(
            'NAV-Session ', self.new, self.created, self._data
        )

    @property
    def new(self) -> bool:
        return self._new

    @property
    def identity(self) -> Optional[Any]:  # type: ignore[misc]
        return self._identity

    @property
    def created(self) -> int:
        return self._created

    @property
    def empty(self) -> bool:
        return not bool(self._data)

    @property
    def max_age(self) -> Optional[int]:
        return self._max_age

    @max_age.setter
    def max_age(self, value: Optional[int]) -> None:
        self._max_age = value

    def changed(self) -> None:
        self._changed = True

    def invalidate(self) -> None:
        self._changed = True
        self._data = {}

    def set_new_identity(self, identity: Optional[Any]) -> None:
        if not self._new:
            raise RuntimeError("Can't change identity for a session which is not new")
        self._identity = identity

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._changed = True
        # also, saved into redis automatically

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._changed = True

class TokenSession(AbstractSession):
    """Memory-based Session."""

    _redis = None

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
            self._encoder = partial(rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601)
            self._decoder = rapidjson.loads
            try:
                self._redis = await self.setup_redis(app)
            except Exception as err:
                print(err)
                return False
        return asyncio.get_event_loop().run_until_complete(_make_mredis())
        self._encoder = partial(
            rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601
        )
    async def get_session(self, request):
        conn = aioredis.Redis(connection_pool=self._redis)
        # change logic: middleware needs to load request['session']
        # getting session based on id on request
        user_token = request['user']
        try:
            data = await conn.get(user_token['id'])
            if data is None:
                logging.debug('Session doesnt Exists or expired')
                # TODO for add a new session explicity
            else:
                data = self._decoder(data)
                session = SessionData(
                    db=self._redis,
                    identity=id,
                    data=data,
                    new=False,
                    max_age=SESSION_TIMEOUT
                )
                return session
        except Exception as err:
            logging.error(err)

    async def load_session(self, request, id, userdata):
        """ Load an existing Session or Create a new One."""
        conn = aioredis.Redis(connection_pool=self._redis)
        data = await conn.get(id)
        if data is None:
            print('MISSING SESSION: ')
            # Session doesn't exists
            session = SessionData(
                db=self._redis,
                identity=id,
                data=userdata,
                new=True,
                max_age=SESSION_TIMEOUT
            )
            try:
                userdata['created'] = time.time()
                # saving this new session on DB
                data = self._encoder(userdata)
                result = await conn.setex(
                    id, SESSION_TIMEOUT, data
                )
            except Exception as err:
                logging.debug(err)
                return False
        else:
            print('SESSION EXISTS: ')
            try:
                data = self._decoder(data)
                session = SessionData(
                    db=self._redis,
                    identity=id,
                    data=data,
                    new=False,
                    max_age=SESSION_TIMEOUT
                )
            except Exception as err:
                logging.debug(err)
                return False
        return session

    async def create(self, request, userdata):
        """Create a new Session Object on Redis Storage."""
        print('START CREATING A NEW SESSION')
        app = request.app
        id = userdata.get('id', None) if userdata else None
        try:
            session = await self.load_session(request, id, userdata)
            last_visit = session["last_visit"] if "last_visit" in session else None
            session["last_visit"] = time.time()
            session["last_visited"] = "Last visited: {}".format(last_visit)
            # Session Data
            request["session"] = session
            request['user'] = userdata
            print(session)
            return session
        except Exception as err:
            logging.error(f'Error creating Session: {err}')
            return False
        return False

    async def invalidate(self, session):
        conn = aioredis.Redis(connection_pool=self._redis)
        try:
            # delete the ID of the session
            result = await conn.delete(session.identity)
            session.invalidate() # invalidate this session object
        except Exception as err:
            print(err)
            logging.error(err)
