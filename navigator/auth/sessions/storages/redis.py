"""Using Redis for Saving Session Storage."""
import time
import uuid
import logging
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
        # print('REDIS CACHE:  ', SESSION_URL, redis)
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

    async def get_session(self, request: web.Request, userdata: dict = {}) -> SessionData:
        try:
            session = request.get(SESSION_OBJECT)
        except Exception as err:
            logging.debug(f'Error on get Session: {err!s}')
            session = None
        if session is None:
            storage = request.get(SESSION_STORAGE)
            if storage is None:
                raise RuntimeError(
                    "Missing Configuration for Session Middleware."
                )
            session = await self.load_session(request, userdata)
        request[SESSION_OBJECT] = session
        request["session"] = session
        return session

    async def invalidate(self, request: web.Request, session: SessionData) -> None:
        conn = aioredis.Redis(connection_pool=self._redis)
        if not session:
            data = None
            session_id = request.get(SESSION_KEY, None)
            if session_id:
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

    async def load_session(
        self,
        request: web.Request,
        userdata: dict = {},
        new: bool = False
    ) -> SessionData:
        """
        Load Session.

        Load User session from backend storage, or create one if
        doesnt exists.

        ---
        new: if False, new session is not created.
        """
        # TODO: first: for security, check if cookie csrf_secure exists
        # if not, session is missed, expired, bad session, etc
        try:
            conn = aioredis.Redis(connection_pool=self._redis)
        except Exception as err:
            logging.exception(f'Error loading Redis Session: {err!s}')
        session_id = request.get(SESSION_KEY, None)
        if not session_id:
            session_id = userdata.get(SESSION_KEY, None) if userdata else None
            # TODO: getting from cookie
        if session_id is None and new is False:
            return False
        # we need to load session data from redis
        print(f':::::: LOAD SESSION FOR {session_id} ::::: ')
        try:
            data = await conn.get(session_id)
        except Exception as err:
            logging.error(f'Error Getting Session data: {err!s}')
            data = None
        if data is None:
            if new is True:
                # create a new session if not exists:
                return await self.new_session(request, userdata)
            else:
                return False
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
            print(f'ERROR: ::::::::::: ', err)
            logging.debug(err)
            session = SessionData(
                db=conn,
                identity=None,
                data=None,
                new=True,
                max_age=self.max_age
            )
        request[SESSION_KEY] = session_id
        session[SESSION_KEY] = session_id
        request[SESSION_OBJECT] = session
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
        if not session_id:
            session_id = self.id_factory()
        if session.empty:
            data = {}
        data = self._encoder(session.session_data())
        max_age = session.max_age
        expire = max_age if max_age is not None else 0
        try:
            conn = aioredis.Redis(connection_pool=self._redis)
            result = await conn.set(
                session_id, data, self.max_age
            )
        except Exception as err:
            print('Error Saving Session: ', err)
            logging.exception(err)
            return False

    async def new_session(
        self,
        request: web.Request,
        data: dict = None
    ) -> SessionData:
        """Create a New Session Object for this User."""
        session_id = request.get(SESSION_KEY, None)
        if not session_id:
            try:
                session_id = data[SESSION_KEY]
            except KeyError:
                session_id = self.id_factory()
        print(f':::::: START CREATING A NEW SESSION FOR {session_id} ::::: ')
        if not data:
            data = {}
        # saving this new session on DB
        try:
            conn = aioredis.Redis(connection_pool=self._redis)
            t = time.time()
            data['created'] = t
            data['last_visit'] = t
            data["last_visited"] = f"Last visited: {t!s}"
            data[SESSION_KEY] = session_id
            dt = self._encoder(data)
            result = await conn.set(
                session_id, dt, self.max_age
            )
            logging.info(f'Creation of New Session: {result}')
            dd = await conn.get(session_id)
        except Exception as err:
            logging.exception(err)
            return False
        try:
            session = SessionData(
                db=conn,
                identity=session_id,
                data=data,
                new=True,
                max_age=self.max_age
            )
        except Exception as err:
            print(err)
            logging.exception(f'Error creating Session Data: {err!s}')
        # Saving Session Object:
        session[SESSION_KEY] = session_id
        request[SESSION_OBJECT] = session
        request[SESSION_KEY] = session_id
        request["session"] = session
        return session
