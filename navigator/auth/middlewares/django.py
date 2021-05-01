import base64
import rapidjson
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX
)

async def django_middleware(app, handler):
    async def middleware(request):
        request.user = None
        try:
            session = request.headers.get("sessionid", None)
        except Exception as e:
            print(e)
            session = request.headers.get("X-Sessionid", None)
        if session:
            redis = app['redis']
            try:
                result = await redis.get("{}:{}".format(SESSION_PREFIX, session))
                print(result)
                if not result:
                    return web.json_response(
                        {'message': 'Invalid Django Session'}, status=400
                    )
                try:
                    session_data = data.decode("utf-8").split(":", 1)
                    user = rapidjson.loads(session_data[1])
                    session = {
                        "key": session,
                        "session_id": session_data[0],
                        **user
                    }
                    print(session)
                    request['session'] = session
                except Exception as err:
                    return web.json_response(
                        {'message': 'Error Decoding Django Session'}, status=400
                    )
            except Exception as err:
                print(err)
                return web.json_response(
                    {'message': 'Invalid Session'}, status=400
                )
        return await handler(request)
    return middleware
