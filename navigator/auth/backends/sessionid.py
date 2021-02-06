"""Django Session Backend.

Navigator Authentication using Django Session Backend
"""
import base64
import rapidjson
import logging
from aiohttp import web
from .base import BaseAuthHandler
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX
)


class SessionIDAuth(BaseAuthHandler):
    """Django SessionID Authentication Handler."""

    async def validate_session(self, key: str = None):
        try:
            result = self.redis.get("{}:{}".format(SESSION_PREFIX, key))
            if not result:
                return False
            data = base64.b64decode(result)
            session_data = data.decode("utf-8").split(":", 1)
            session = {
                "key": key,
                "session_id": session_data[0],
                "user": rapidjson.loads(session_data[1])
            }
            return session
        except Exception as err:
            print(err)
            logging.debug("Django Session Decoding Error: {}".format(err))
            return False

    async def get_payload(self, request):
        try:
            id = request.headers.get("sessionid", None)
        except Exception as e:
            print(e)
            id = request.headers.get("X-Sessionid", None)
        if not id:
            return None

    async def check_credentials(self, request):
        try:
            sessionid = await self.get_payload(request)
        except Exception:
            return False
        if not sessionid:
            return False
        else:
            try:
                # making validation
                user = await self.validate_session(request, key=sessionid)
                print(user)
                return user
            except Exception as err:
                print(err)
                return False
            else:
                return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            sessionid = request.headers.get('X-Sessionid', None)
            if sessionid:
                session = await get_session(request)
                if session['key'] != sessionid:
                    return web.json_response(
                        {'message': 'Unauthorized'}, status=403
                    )
            return await handler(request)
        return middleware
