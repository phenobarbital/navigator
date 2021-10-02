"""Django Session Backend.

Navigator Authentication using Django Session Backend
description: read the Django session from Redis Backend
and decrypt, after that, a session will be created.
"""
import base64
import rapidjson
import logging
import asyncio

# redis pool
import aioredis
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_URL,
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX,
    SESSION_KEY
)


class DjangoAuth(BaseAuthBackend):
    """Django SessionID Authentication Handler."""

    redis = None
    _scheme: str = "Bearer"

    def configure(self, app, router):
        async def _setup_redis(app):
            self.redis = aioredis.from_url(
                    SESSION_URL,
                    decode_responses=True,
                    encoding='utf-8'
            )
            async def _close_redis(app):
                await self.redis.close()
            app.on_cleanup.append(_close_redis)
            return self.redis

        asyncio.get_event_loop().run_until_complete(_setup_redis(app))
        # executing parent configurations
        super(DjangoAuth, self).configure(app, router)

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    async def get_payload(self, request):
        id = None
        try:
            if "Authorization" in request.headers:
                try:
                    scheme, id = request.headers.get("Authorization").strip().split(" ")
                except ValueError:
                    raise web.HTTPForbidden(
                        reason="Invalid authorization Header",
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason="Invalid Session scheme",
                    )
            elif "X-Sessionid" in request.headers:
                id = request.headers.get("X-Sessionid", None)
        except Exception as e:
            print(e)
            return None
        return id

    async def validate_session(self, key: str = None):
        try:
            async with await self.redis as redis:
                result = await redis.get("{}:{}".format(SESSION_PREFIX, key))
            if not result:
                raise Exception('Empty or non-existing Session')
            data = base64.b64decode(result)
            session_data = data.decode("utf-8").split(":", 1)
            user = rapidjson.loads(session_data[1])
            session = {
                "key": key,
                "session_id": session_data[0],
                self.user_property: user,
            }
            return session
        except Exception as err:
            logging.debug("Django Decoding Error: {}".format(err))
            raise Exception("Django Decoding Error: {}".format(err))

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {self.userid_attribute: login}
        try:
            user = await self.get_user(**search)
            return user
        except UserDoesntExists as err:
            raise UserDoesntExists(f"User {login} doesn\'t exists")
        except Exception as err:
            raise Exception(err)
        return None

    async def authenticate(self, request):
        """ Authenticate against user credentials (django session id)."""
        try:
            sessionid = await self.get_payload(request)
            logging.debug(f"Session ID: {sessionid}")
        except Exception as err:
            raise NavException(err, state=400)
        if not sessionid:
            raise InvalidAuth(
                "Auth: Invalid Credentials",
                state=401
            )
        else:
            try:
                data = await self.validate_session(key=sessionid)
            except Exception as err:
                raise InvalidAuth(f"Invalid Session: {err!s}", state=401)
            # making validation
            if not data:
                raise InvalidAuth("Missing User Information", state=403)
            try:
                u = data[self.user_property]
                username = u[self.userid_attribute]
            except KeyError as err:
                print(err)
                raise InvalidAuth(
                    f"Missing {self.userid_attribute} attribute: {err!s}", state=401
                )
            try:
                user = await self.validate_user(login=username)
            except UserDoesntExists as err:
                raise UserDoesntExists(err)
            except Exception as err:
                raise NavException(err, state=500)
            try:
                userdata = self.get_userdata(user)
                userdata["session"] = data
                userdata[self.session_key_property] = sessionid
                # saving user-data into request:
                request['userdata'] = userdata
                request[SESSION_KEY] = sessionid
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: user[self.username_attribute],
                    self.userid_attribute: user[self.userid_attribute],
                    self.session_key_property: sessionid
                }
                token = self.create_jwt(
                    data=payload
                )
                return {
                    "token": token,
                    **userdata
                }
            except Exception as err:
                print(err)
                return False
