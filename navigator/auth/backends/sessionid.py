"""Django Session Backend.

Navigator Authentication using Django Session Backend
"""
import base64
import rapidjson
import logging
import asyncio
# redis pool
import aioredis
from aiohttp import web, hdrs
from .base import BaseAuthHandler
from datetime import datetime, timedelta
from aiohttp_session import get_session
from navigator.conf import (
    SESSION_URL,
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX
)


class SessionIDAuth(BaseAuthHandler):
    """Django SessionID Authentication Handler."""
    redis = None
    _scheme: str = 'Session'

    def configure(self):
        async def _make_redis():
            try:
                self.redis = await aioredis.create_redis_pool(
                    SESSION_URL, timeout=1
                )
            except Exception as err:
                print(err)
                raise Exception(err)
        asyncio.get_event_loop().run_until_complete(
            _make_redis()
        )


    async def validate_session(self, key: str = None):
        try:
            result = await self.redis.get("{}:{}".format(SESSION_PREFIX, key))
            if not result:
                return False
            data = base64.b64decode(result)
            session_data = data.decode("utf-8").split(":", 1)
            user = rapidjson.loads(session_data[1])
            session = {
                "key": key,
                "session_id": session_data[0],
                self.user_property: user
            }
            return session
        except Exception as err:
            print(err)
            logging.debug("Django Session Decoding Error: {}".format(err))
            return False

    async def get_payload(self, request):
        id = None
        try:
            if 'Authorization' in request.headers:
                try:
                    scheme, id = request.headers.get(
                        'Authorization'
                    ).strip().split(' ')
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Header',
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason='Invalid Session scheme',
                    )
            elif 'X-Sessionid' in request.headers:
                id = request.headers.get('X-Sessionid', None)
        except Exception as e:
            print(e)
            return None
        return id

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
                user = await self.validate_session(key=sessionid)
                return user
            except Exception as err:
                print(err)
                return False
            else:
                return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return authz
            if 'Authorization' in request.headers:
                try:
                    scheme, sessionid = request.headers.get(
                        'Authorization'
                    ).strip().split(' ')
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Header',
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason='Invalid Session scheme',
                    )
            elif 'X-Sessionid' in request.headers:
                sessionid = request.headers.get('X-Sessionid', None)
            else:
                if self.credentials_required is True:
                    raise web.HTTPUnauthorized(
                        reason='Missing Authorization Session',
                    )
                else:
                    sessionid = None
            if sessionid:
                session = await get_session(request)
                if self.credentials_required is True:
                    try:
                        user = session[self.user_property]
                    except KeyError:
                        return web.json_response(
                            {'message': 'Invalid Session Information'}, status=400
                        )
                    if user['key'] != sessionid:
                        return web.json_response(
                            {'message': 'Unauthorized: Invalid Session'}, status=403
                        )
            return await handler(request)
        return middleware
