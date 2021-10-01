"""User sessions for Navigator and aiohttp.web server."""

__version__ = '0.0.1'

import abc
from aiohttp import web
import aioredis
import rapidjson
import asyncio
import time
import uuid
import logging
from functools import wraps, partial
from aiohttp.web_middlewares import _Handler, _Middleware
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Iterator,
    Mapping,
    MutableMapping,
    Optional
)
from navigator.conf import (
    SESSION_URL,
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_KEY
)

SESSION_STORAGE = 'NAVIGATOR_SESSION_STORAGE'
SESSION_OBJECT = 'NAV_SESSION'

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

    @property
    def is_changed(self): -> bool:
        return self._changed

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


class AbstractStorage(metaclass=abc.ABCMeta):
    key_factory: Callable = lambda: uuid.uuid4().hex
    def __init__(self, max_age: int = None, secure: bool = None) -> None:
        if not max_age:
            self.max_age = SESSION_TIMEOUT
        else:
            self.max_age = max_age

    def configure_session(self, app: web.Application) -> None:
        """Configure the Middleware for NAV Session."""
        app.middlewares.append(
            session_middleware(app, self)
        )

    @abc.abstractmethod
    async def new_session(
        self,
        request: web.Request,
        data: Dict = None
    ) -> SessionData:
        pass

    @abc.abstractmethod
    async def load_session(self, request: web.Request) -> SessionData:
        pass

    @abc.abstractmethod
    async def save_session(self,
        request: web.Request,
        response: web.StreamResponse,
        session: SessionData
    ) -> None:
        pass


class TestStorage(AbstractStorage):
    """Test version of Session Handler."""
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

    def configure_session(self, app: web.Application) -> None:
        super(TestStorage, self).configure_session(app)
        self._encoder = partial(
            rapidjson.dumps, datetime_mode=rapidjson.DM_ISO8601
        )
        self._decoder = rapidjson.loads
        async def _make_mredis():
            try:
                self._redis = await self.setup_redis(app)
            except Exception as err:
                print(err)
                return False
        return asyncio.get_event_loop().run_until_complete(_make_mredis())

    async def load_session(self, request: web.Request, userdata: Dict = None) -> SessionData:
        # first: for security, check if cookie csrf_secure exists
        # if not, session is missed, expired, bad session, etc
        conn = aioredis.Redis(connection_pool=self._redis)
        session_id = userdata.get(SESSION_KEY, None) if userdata else None
        if not session_id:
            # TODO: getting from cookie
            pass
        # we need to load session data from redis
        data = await conn.get(session_id)
        if data is None:
            return await self.new_session(request, userdata)
        try:
            data = self._decoder(data)
            session = SessionData(
                db=conn,
                identity=session_id,
                data=data,
                new=False,
                max_age=self.max_age
            )
        except Exception as err:
            logging.debug(err)
            session = SessionData(
                db=conn,
                identity=None,
                data=None,
                new=True,
                max_age=self.max_age
            )
        # if not data from redis, invoke new_session(request, userdata)
        last_visit = session["last_visit"] if "last_visit" in session else None
        session["last_visited"] = "Last visited: {}".format(last_visit)
        return session

    async def save_session(self,
        request: web.Request,
        response: web.StreamResponse,
        session: SessionData
    ) -> None:
        pass

    async def new_session(
        self,
        request: web.Request,
        data: Dict = None
    ) -> SessionData:
        """Create a New Session Object for this User."""
        print(':::::: START CREATING A NEW SESSION ::::: ')
        session_id = data.get(SESSION_KEY, None) if data else self.key_factory()
        if not data:
            data = {}
        data['created'] = time.time()
        # saving this new session on DB
        conn = aioredis.Redis(connection_pool=self._redis)
        try:
            dt = self._encoder(data)
            result = await conn.setex(
                session_id, self.max_age, dt
            )
        except Exception as err:
            logging.debug(err)
            return False
        session = SessionData(
            db=conn,
            identity=session_id,
            data=data,
            new=True,
            max_age=self.max_age
        )
        # Saving Session Object:
        print(':::: SAVING SESSION OBJECT ::: ')
        t = time.time()
        session["last_visit"] = t
        session["last_visited"] = f"Last visited: {t!s}"
        session[SESSION_KEY] = session_id
        request[SESSION_OBJECT] = session
        return session

async def new_session(request: web.Request) -> SessionData:
    storage = request.get(SESSION_STORAGE)
    if storage is None:
        raise RuntimeError(
            "Missing Configuration for Session Middleware."
        )
    session = await storage.new_session()
    if not isinstance(session, SessionData):
        raise RuntimeError(
            "Installed {!r} storage should return session instance "
            "on .load_session() call, got {!r}.".format(storage, session))
    request[SESSION_OBJECT] = session
    return session

async def get_session(request: web.Request, userdata: dict = None) -> SessionData:
    session = request.get(SESSION_OBJECT)
    print('SESSION IS: ', session)
    if session is None:
        storage = request.get(SESSION_STORAGE)
        print('STORAGE IS ', storage)
        if storage is None:
            raise RuntimeError(
                "Missing Configuration for Session Middleware."
            )
        # using the storage session for Load an existing Session
        session = await storage.load_session(request, userdata)
        if not isinstance(session, SessionData):
            raise RuntimeError(
                "Installed {!r} storage should return session instance "
                "on .load_session() call, got {!r}.".format(storage, session))
        request[SESSION_OBJECT] = session
    return session

def session_middleware(
        app: web.Application,
        storage: 'AbstractStorage'
) -> _Middleware:
    """Middleware to attach Session Storage to every Request."""
    if not isinstance(storage, AbstractStorage):
        raise RuntimeError(f"Expected an AbstractStorage got {storage!s}")

    @web.middleware
    async def middleware(
            request: web.Request,
            handler: _Handler
    ) -> web.StreamResponse:
        request[SESSION_STORAGE] = storage
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            raise exc
        if not isinstance(response, (web.StreamResponse, web.HTTPException)):
            # likely got websocket or streaming
            return response
        if response.prepared:
            raise RuntimeError(
                "We Cannot save session data into on prepared responses"
            )
        session = request.get(SESSION_OBJECT)
        if session is not None:
            if session.is_changed:
                await storage.save_session(request, response, session)
        print('Y AQUI TERMINA EL SESSION MIDDLEWARE')
        return response

    return middleware
