import base64
import rapidjson
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import SESSION_TIMEOUT, SECRET_KEY, SESSION_PREFIX
from aiohttp_session import get_session
import logging

async def django_middleware(app, handler):
    async def middleware(request):
        request.user = None
        try:
            sessionid = request.headers.get("X-Sessionid")
        except Exception as e:
            sessionid = request.headers.get("Sessionid", None)
            logging.warning('Django Middleware: Using Sessionid (instead X-Sessionid) is deprecated and will be removed soon')
        redis = app["redis"]
        session = await get_session(request)
        if sessionid in session:
            data = session[sessionid]
            request["user_id"] = data["user_id"]
            request["session"] = data
            # this session already exists:
            return await handler(request)
        try:
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
                request["user_id"] = user["user_id"]
                request["session"] = data
                session[sessionid] = data
            except Exception as err:
                print(err)
                return web.json_response(
                    {"message": "Error Decoding Django Session"}, status=400
                )
        except Exception as err:
            print(err)
            return web.json_response({"message": "Invalid Session"}, status=400)
        return await handler(request)

    return middleware
