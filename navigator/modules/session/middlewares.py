from typing import Any, Callable, Dict, List, Optional

#import ujson as json
import json
# TODO: using rapidjson
from aiohttp import web
from aiohttp.web import middleware

from navigator.middlewares import check_path

# TODO: Middleware Class to avoid repeat check_path($0)


@middleware
async def django_session(request, handler):
    id = None
    if not check_path(request.path):
        return await handler(request)
    try:
        id = request.headers.get("sessionid", None)
    except Exception as e:
        print(e)
        id = request.headers.get("X-Sessionid", None)
    if id is not None:
        session = None
        try:
            # first: clear session
            session = request.app["session"]
            await session.logout()  # clear existing session
            if not await session.decode(key=id):
                message = {
                    "code": 403,
                    "message": "Invalid Session",
                    "reason": "Unknown Session ID",
                }
                return web.json_response({"error": message}, status=403)
        except Exception as err:
            print("Error Decoding Session: {}, {}".format(err, err.__class__))
            return await handler(request)
        try:
            request["user_id"] = session["user_id"]
            request["session"] = session
        except Exception as err:
            # TODO: response to an auth error
            message = {
                "code": 403,
                "message": "Invalid Session or Authentication Error",
                "reason": str(err),
            }
            return web.json_response({"error": message}, status=403)
        finally:
            return await handler(request)
    else:
        # TODO: authorization
        return await handler(request)
