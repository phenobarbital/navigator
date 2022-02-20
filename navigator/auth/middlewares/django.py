import base64
import rapidjson
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SESSION_KEY,
    SECRET_KEY,
    SESSION_PREFIX,
    CREDENTIALS_REQUIRED,
    SESSION_STORAGE,
    SESSION_USER_PROPERTY
)
from navigator.auth.sessions import get_session, new_session
import logging
import time

def get_sessionid(request: web.Request):
    sessionid = request.headers.get("X-Sessionid")
    if not sessionid:
        raise web.HTTPBadRequest(
            reason=f'Django Middleware: use Header different from X-Sessionid is not available'
        )
    return sessionid

async def django_middleware(app, handler):
    async def middleware(request):
        sessionid = get_sessionid(request)
        request.user = None
        if not sessionid:
            if CREDENTIALS_REQUIRED is True:
                raise web.HTTPUnauthorized(
                    reason="Django Middleware: Missing Session and Auth is Required"
                )
            return await handler(request)
        try:
            request[SESSION_KEY] = sessionid
            session = await get_session(
                request, new = False
            )
            if not session:
                # we need to create a new one
                session = await new_session(request)
            else:
                id = session.get(SESSION_KEY, None)
                if id != sessionid:
                    # this is another user or an empty session:
                    session = request[SESSION_STORAGE]
                    await session.forgot(request)
                    request[SESSION_KEY] = sessionid
                    session = await new_session(request)
                else:
                    data = session[sessionid]
                    request[SESSION_KEY] = sessionid
                    request[SESSION_USER_PROPERTY] = data
                    request["user_id"] = data["user_id"]
                    request["session"] = data
                    # this session already exists:
                    return await handler(request)
        except Exception as err:
            raise web.HTTPBadRequest(
                reason=f"Django Middleware: Error on Session: {err!s}"
            )
        try:
            # Fallback: recalculate again the session ID
            redis = app["redis"]
            result = await redis.get("{}:{}".format(SESSION_PREFIX, sessionid))
            if not result:
                raise web.HTTPBadRequest(
                    reason="Django Middleware: Invalid Django Session"
                )
            try:
                data = base64.b64decode(result)
                session_data = data.decode("utf-8").split(":", 1)
                user = rapidjson.loads(session_data[1])
                data = {
                    "key": sessionid,
                    "session_id": session_data[0],
                    **user
                }
                request["user_id"] = user["user_id"]
                request["session"] = data
                request[SESSION_USER_PROPERTY] = data
                session["session"] = data # fallback compatibility
            except Exception as err:
                raise web.HTTPBadRequest(
                    reason=f'Django Mid: Error decoding Django Session {err!s}'
                )
        except Exception as err:
            print(err)
            if CREDENTIALS_REQUIRED is True:
                raise web.HTTPForbidden(
                    reason='Access is Restricted'
                )
        return await handler(request)

    return middleware
