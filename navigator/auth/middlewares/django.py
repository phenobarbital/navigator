import base64
import rapidjson
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SESSION_KEY,
    SECRET_KEY,
    SESSION_PREFIX,
    AUTH_CREDENTIALS_REQUIRED,
    SESSION_STORAGE
)
from navigator.auth.sessions import get_session, new_session
import logging
import time

def get_sessionid(request):
    sessionid = request.headers.get("X-Sessionid")
    if not sessionid:
        sessionid = request.headers.get("sessionid", None)
        logging.warning(
            'Django Middleware: Using Sessionid (instead X-Sessionid) is deprecated and will be removed soon'
        )
    return sessionid

async def django_middleware(app, handler):
    async def middleware(request):
        sessionid = get_sessionid(request)
        if not sessionid:
            if AUTH_CREDENTIALS_REQUIRED is True:
                request[SESSION_KEY] = None
                raise web.HTTPUnauthorized(
                    reason="Missing Session and Auth Required"
                )
            return await handler(request)
        try:
            request[SESSION_KEY] = sessionid
            session = await get_session(request, new = False)
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
                    request["user_id"] = data["user_id"]
                    request["session"] = data
                    # this session already exists:
                    return await handler(request)
        except Exception as err:
            print(err)
            raise web.HTTPBadRequest(
                reason=f"Unknown Error on Django Middleware: {err!s}"
            )
        try:
            # Fallback: recalculate again the session ID
            redis = app["redis"]
            result = await redis.get("{}:{}".format(SESSION_PREFIX, sessionid))
            if not result:
                raise web.HTTPBadRequest(
                    reason="Invalid Django Session"
                )
            try:
                data = base64.b64decode(result)
                session_data = data.decode("utf-8").split(":", 1)
                user = rapidjson.loads(session_data[1])
                print(user)
                data = {
                    "key": sessionid,
                    "session_id": session_data[0],
                    **user
                }
                request["user_id"] = user["user_id"]
                request["session"] = data
                # session.set_data(data)
                session["session"] = data
            except Exception as err:
                print(err)
                return web.json_response(
                    {"message": "Error Decoding Django Session"}, status=400
                )
        except Exception as err:
            print(err)
            if AUTH_CREDENTIALS_REQUIRED is True:
                return web.json_response(
                    {"error:": str(err), "message": "Invalid Session"},
                    status=400
                )
        return await handler(request)

    return middleware
