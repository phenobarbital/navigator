"""Django Session Backend.

Navigator Authentication using Django Session Backend
description: read the Django session from Redis Backend
and decrypt, after that, a session will be created.
"""
import base64
import logging
from typing import Callable
import aioredis
import orjson
from aiohttp import web
from navigator_session import (
    AUTH_SESSION_OBJECT
)
from navigator.exceptions import (
    NavException,
    UserNotFound,
    InvalidAuth
)
from navigator.conf import (
    DJANGO_USER_MAPPING,
    DJANGO_SESSION_URL,
    DJANGO_SESSION_PREFIX
)
# User Identity
from navigator.auth.identities import AuthUser, Column
from .base import BaseAuthBackend
class DjangoUser(AuthUser):
    """DjangoUser.

    user authenticated with Django Session (sessionid bearer).
    """
    sessionid: str = Column(required=True)



class DjangoAuth(BaseAuthBackend):
    """Django SessionID Authentication Handler."""
    _user_object: str = 'user'
    _user_id_key: str = '_auth_user_id'
    _ident: AuthUser = DjangoUser

    def __init__(
        self,
        user_attribute: str = None,
        userid_attribute: str = None,
        password_attribute: str = None,
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        self._pool: Callable = None
        super(
            DjangoAuth, self
        ).__init__(
            user_attribute,
            userid_attribute,
            password_attribute,
            credentials_required,
            authorization_backends,
            **kwargs
        )

    def configure(self, app, router, handler):
        async def _setup_redis(app: web.Application):
            self._pool = aioredis.ConnectionPool.from_url(
            # self._redis = aioredis.from_url(
                    DJANGO_SESSION_URL,
                    decode_responses=True,
                    encoding='utf-8'
            )
        app.on_startup.append(_setup_redis)
        # closing:
        async def _close_redis(app: web.Application):
            try:
                await self._pool.disconnect(inuse_connections=True)
            except Exception as e:
                logging.warning(e)
        app.on_cleanup.append(_close_redis)
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
        except Exception:
            return None
        return id

    async def validate_session(self, key: str = None):
        try:
            async with aioredis.Redis(connection_pool=self._pool) as redis:
                result = await redis.get(f"{DJANGO_SESSION_PREFIX}:{key}")
            if not result:
                raise Exception('Django Auth: non-existing Session')
            data = base64.b64decode(result)
            session_data = data.decode("utf-8").split(":", 1)
            user = orjson.loads(session_data[1])
            try:
                if not 'user_id' in user:
                    user['user_id'] = user[self._user_id_key]
            except KeyError:
                logging.error(
                    'DjangoAuth: Current User Data missing User ID'
                )
            session = {
                "key": key,
                "session_id": session_data[0],
                self.user_property: user,
            }
            return session
        except Exception as err:
            print('EEEE ', err )
            logging.debug(
                f"Django Decoding Error: {err}"
            )
            raise

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {self.userid_attribute: login}
        try:
            user = await self.get_user(**search)
            return user
        except UserNotFound as err:
            raise UserNotFound(
                f"User {login} doesn\'t exists"
            ) from err
        except Exception as e:
            raise Exception(e) from e

    async def authenticate(self, request):
        """ Authenticate against user credentials (django session id)."""
        try:
            sessionid = await self.get_payload(request)
            logging.debug(f"Session ID: {sessionid}")
        except Exception as err:
            raise NavException(
                err, state=400
            ) from err
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
                raise InvalidAuth(
                    f"{err!s}", state=401
                ) from err
            if not data:
                raise InvalidAuth(
                    "Django Auth: Missing User Info",
                    state=403
                )
            try:
                u = data[self.user_property]
                username = u[self.userid_attribute]
            except KeyError as err:
                raise InvalidAuth(
                    f"Missing {self.userid_attribute} attribute: {err!s}",
                    state=401
                ) from err
            try:
                user = await self.validate_user(
                    login=username
                )
            except UserNotFound as err:
                raise UserNotFound(err) from err
            except Exception as err:
                raise NavException(err, state=500) from err
            try:
                userdata = self.get_userdata(user)
                # extract data from Django Session to Session Object:
                udata = {}
                for k, v in data[self._user_object].items():
                    if k in DJANGO_USER_MAPPING.keys():
                        if k in userdata:
                            if isinstance(userdata[k], list):
                                # if userdata of k is a list, we need to mix with data:
                                udata[k] = v + userdata[k]
                            elif isinstance(userdata[k], dict):
                                udata[k] = {**v, ** userdata[k]}
                            else:
                                # data override current employee data.
                                udata[k] = v
                        else:
                            udata[k] = v
                try:
                    # merging both session objects
                    userdata[AUTH_SESSION_OBJECT] = {
                        **userdata[AUTH_SESSION_OBJECT],
                        **data,
                        **udata
                    }
                    usr = await self.create_user(
                        userdata[AUTH_SESSION_OBJECT]
                    )
                    usr.id = sessionid
                    usr.sessionid = sessionid
                    usr.set(self.username_attribute, user[self.username_attribute])
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
