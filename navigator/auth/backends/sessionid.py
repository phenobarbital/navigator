"""Django Session Backend.

Navigator Authentication using Django Session Backend
description: read the Django session from Redis Backend and decrypt.
"""
import base64
import rapidjson
import logging
import asyncio
# redis pool
import aioredis
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_URL,
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX
)


class SessionIDAuth(BaseAuthBackend):
    """Django SessionID Authentication Handler."""
    redis = None
    _scheme: str = 'Bearer'

    def configure(self, app, router):
        async def _make_redis():
            try:
                self.redis = await aioredis.from_url(
                    SESSION_URL, timeout=1
                )
            except Exception as err:
                print(err)
                raise Exception(err)
        asyncio.get_event_loop().run_until_complete(
            _make_redis()
        )
        # executing parent configurations
        super(SessionIDAuth, self).configure(app, router)

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

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {
            self.userid_attribute: login
        }
        try:
            user = await self.get_user(**search)
            return user
        except UserDoesntExists as err:
            raise UserDoesntExists(f'User {login} doesnt exists')
        except Exception as err:
            raise Exception(err)
        return None

    async def check_credentials(self, request):
        try:
            sessionid = await self.get_payload(request)
            logging.debug(f'Session ID: {sessionid}')
        except Exception as err:
            raise NavException(err, state=400)
        if not sessionid:
            raise InvalidAuth('Invalid Credentials', state=401)
        else:
            # getting user information
            # TODO: making the validation of token and expiration
            try:
                data = await self.validate_session(key=sessionid)
            except Exception as err:
                raise InvalidAuth(f'Invalid Session: {err!s}', state=401)
            # making validation
            try:
                u = data[self.user_property]
                username = u[self.userid_attribute]
            except KeyError as err:
                print(err)
                raise InvalidAuth(
                    f'Missing {self.userid_attribute} attribute: {err!s}',
                    state=401
                )
            try:
                user = await self.validate_user(
                    login=username
                )
            except UserDoesntExists as err:
                raise UserDoesntExists(err)
            except Exception as err:
                raise NavException(err, state=500)
            try:
                userdata = self.get_userdata(user)
                userdata['session'] = data
                # Create the User session and returned.
                session = await self._session.create_session(
                    request,
                    user,
                    userdata
                )
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: user[self.username_attribute],
                    'user_id': user[self.userid_attribute]
                }
                token = self.create_jwt(data=payload)
                return {'token': token}
            except Exception as err:
                print(err)
                return False

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        pass

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return await authz
            if 'Authorization' in request.headers:
                try:
                    jwt_token = self.decode_token(request)
                except NavException as err:
                    response = {
                        "message": "Session ID Failure",
                        "error": err.message,
                        "status": err.state
                    }
                    return web.json_response(response, status=err.state)
                except Exception as err:
                    raise web.HTTPBadRequest(
                        body=f'Bad Request: {err!s}'
                    )
                if self.credentials_required is True:
                    raise web.HTTPUnauthorized(
                        body='Unauthorized'
                    )
            elif 'X-Sessionid' in request.headers:
                sessionid = request.headers.get('X-Sessionid', None)
                try:
                    data = await self.validate_session(key=sessionid)
                    # TODO: making validation using only sessionid
                except Exception as err:
                    raise web.HTTPUnauthorized(
                        reason='Invalid Authorization Session',
                    )
            else:
                if self.credentials_required is True:
                    raise web.HTTPUnauthorized(
                        reason='Missing Authorization Session',
                    )
            return await handler(request)
        return middleware
