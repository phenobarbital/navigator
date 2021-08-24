import base64
import rapidjson
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX,
    CREDENTIALS_REQUIRED
)
from aiohttp_session import get_session, new_session
import logging
import time

def get_sessionid(request):
    sessionid = request.headers.get("X-Sessionid")
    if not sessionid:
        sessionid = request.headers.get("sessionid", None)
        logging.warning('Django Middleware: Using Sessionid (instead X-Sessionid) is deprecated and will be removed soon')
    return sessionid

async def django_middleware(app, handler):
    async def middleware(request):
        request.user = None
        sessionid = get_sessionid(request)
        if not sessionid:
            session = await get_session(request)
            session.invalidate()
            if CREDENTIALS_REQUIRED is True:
                return web.json_response(
                    {"error:": str(err), "message": "Missing Session and Auth Required"},
                    status=403
                )
            return await handler(request)
        try:
            session = await get_session(request)
        except Exception as e:
            print(e)
            session = await new_session(request)
        try:
            id = session['id']
            if id != sessionid:
                session = await new_session(request)
        except KeyError:
            pass # new session
        if sessionid in session:
            data = session[sessionid]
            session['id'] = sessionid
            request["user_id"] = data["user_id"]
            request["session"] = data
            # this session already exists:
            return await handler(request)
        try:
            redis = app["redis"]
            result = await redis.get("{}:{}".format(SESSION_PREFIX, sessionid))
            if not result:
                return web.json_response(
                    {"message": "Invalid Django Session"}, status=400
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
                # print('DATA DUMP: ', data)
                request["user_id"] = user["user_id"]
                request["session"] = data
                session['id'] = sessionid
                session[sessionid] = data
            except Exception as err:
                print(err)
                return web.json_response(
                    {"message": "Error Decoding Django Session"}, status=400
                )
        except Exception as err:
            print(err)
            if CREDENTIALS_REQUIRED is True:
                return web.json_response(
                    {"error:": str(err), "message": "Invalid Session"},
                    status=400
                )
        return await handler(request)

    return middleware
