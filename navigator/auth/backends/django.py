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
from aiohttp import web
from .base import BaseAuthBackend
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from navigator.conf import (
    SESSION_URL,
    SESSION_TIMEOUT,
    SECRET_KEY,
    SESSION_PREFIX,
    SESSION_KEY,
    AUTH_SESSION_OBJECT
)

# User Identity
from navigator.auth.identities import AuthUser, Column

class DjangoUser(AuthUser):
    """DjangoUser.
    
    user authenticated with Django Session (sessionid bearer).
    """
    sessionid: str = Column(required=True)



class DjangoAuth(BaseAuthBackend):
    """Django SessionID Authentication Handler."""

    def configure(self, app, router, handler):
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
        super(DjangoAuth, self).configure(app, router, handler)

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
                if scheme != self.scheme:
                    raise web.HTTPForbidden(
                        reason="Invalid Session scheme",
                    )
            elif "x-sessionid" in request.headers:
                id = request.headers.get("x-sessionid", None)
        except Exception as e:
            return None
        return id

    async def validate_session(self, key: str = None):
        try:
            async with await self.redis as redis:
                result = await redis.get("{}:{}".format(SESSION_PREFIX, key))
            if not result:
                raise Exception('Django Auth: non-existing Session')
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
            raise

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {self.userid_attribute: login}
        try:
            user = await self.get_user(**search)
            return user
        except UserDoesntExists as err:
            raise UserDoesntExists(f"User {login} doesn\'t exists")
        except Exception:
            raise
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
                "Django Auth: Missing Credentials",
                state=401
            )
        else:
            try:
                data = await self.validate_session(
                    key=sessionid
                )
            except Exception as err:
                raise InvalidAuth(f"{err!s}", state=401)
            # making validation
            if not data:
                raise InvalidAuth("Django Auth: Missing User Info", state=403)
            try:
                u = data[self.user_property]
                username = u[self.userid_attribute]
            except KeyError as err:
                raise InvalidAuth(
                    f"Missing {self.userid_attribute} attribute: {err!s}",
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
                try:
                    # merging both session objects
                    userdata[AUTH_SESSION_OBJECT] = {
                        **userdata[AUTH_SESSION_OBJECT],
                        **data
                    }
                    usr = DjangoUser(data=userdata[AUTH_SESSION_OBJECT])
                    usr.id = sessionid
                    usr.sessionid = sessionid
                    usr.set(self.username_attribute, user[self.username_attribute])
                    logging.debug(f'User Created > {usr}')
                except Exception as err:
                    logging.exception(err)
                userdata[self.session_key_property] = sessionid
                # saving user-data into request:
                await self.remember(
                    request, sessionid, userdata, usr
                )
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
                logging.exception(f'DjangoAuth: Authentication Error: {err}')
                return False
