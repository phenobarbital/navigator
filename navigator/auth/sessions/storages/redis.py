"""Using Redis for Saving Session Storage."""
import time
import aioredis
import asyncio
import rapidjson
from aiohttp import web
from .abstract import AbstractStorage, SessionData
from functools import wraps, partial
from navigator.conf import (
    SESSION_URL,
    SESSION_KEY,
    SESSION_OBJECT,
    SESSION_STORAGE
)

class RedisStorage(AbstractStorage):
    """Test version of Session Handler."""
    _redis = None

    async def setup_redis(self, app: web.Application):
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
        super(RedisStorage, self).configure_session(app)
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

    async def get_session(self, request: web.Request) -> SessionData:
        session = request.get(SESSION_OBJECT)
        if session is None:
            storage = request.get(SESSION_STORAGE)
            if storage is None:
                raise RuntimeError(
                    "Missing Configuration for Session Middleware."
                )
            session = await storage.load_session(request, userdata)
        request[SESSION_OBJECT] = session
        request["session"] = session
        return session

    async def invalidate(self, request: web.Request, session: SessionData) -> None:
        conn = aioredis.Redis(connection_pool=self._redis)
        if session is None:
            session_id = request.get(SESSION_KEY, None) if userdata else None
            data = await conn.get(session_id)
            if data is None:
                # nothing to forgot
                return True
        try:
            # delete the ID of the session
            result = await conn.delete(session.identity)
            session.invalidate() # invalidate this session object
        except Exception as err:
            logging.error(err)
            return False
        return True

    async def load_session(self, request: web.Request, userdata: dict = None) -> SessionData:
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
        request[SESSION_KEY] = session_id
        request["session"] = session
        return session

    async def save_session(self,
        request: web.Request,
        response: web.StreamResponse,
        session: SessionData
    ) -> None:
        """Save the whole session in the backend Storage."""
        session_id = session.identity
        if not session_id:
            session_id = session.get(SESSION_KEY, None)
        if session_id is None:
            session_id = self.key_factory()
        if session.empty:
            data = {}
        data = self._encoder(session.session_data())
        max_age = session.max_age
        expire = max_age if max_age is not None else 0
        conn = aioredis.Redis(connection_pool=self._redis)
        try:
            result = await conn.setex(
                session_id, self.max_age, dt
            )
        except Exception as err:
            logging.debug(err)
            return False

    async def new_session(
        self,
        request: web.Request,
        data: dict = None
    ) -> SessionData:
        """Create a New Session Object for this User."""
        # print(':::::: START CREATING A NEW SESSION ::::: ')
        session_id = data.get(SESSION_KEY, None) if data else self.key_factory()
        if not data:
            data = {}
        t = time.time()
        data['created'] = t
        data['last_visit'] = t
        data["last_visited"] = f"Last visited: {t!s}"
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
        # print(':::: SAVING SESSION OBJECT ::: ')
        session[SESSION_KEY] = session_id
        request[SESSION_OBJECT] = session
        request[SESSION_KEY] = session_id
        request["session"] = session
        return session
