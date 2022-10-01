import logging
import asyncio
from collections.abc import Callable
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from functools import partial, wraps
from concurrent.futures import ThreadPoolExecutor
import base64
import jwt
from cryptography import fernet
from aiohttp import web, hdrs
from aiohttp.web_urldispatcher import SystemRoute
from asyncdb.models import Model
from navigator_session import (
    new_session,
    AUTH_SESSION_OBJECT,
    SESSION_TIMEOUT,
    SESSION_KEY,
    SESSION_USER_PROPERTY
)
from navigator.exceptions import (
    NavException,
    UserNotFound,
    InvalidAuth,
    FailedAuth,
    AuthExpired
)
from navigator.conf import (
    AUTH_USERNAME_ATTRIBUTE,
    AUTH_JWT_ALGORITHM,
    USER_MAPPING,
    CREDENTIALS_REQUIRED,
    SECRET_KEY
)
# Authenticated Identity
from navigator.auth.identities import Identity

exclude_list = (
    "/static/",
    "/api/v1/login",
    "/api/v1/logout",
    "/login",
    "/logout",
    "/signin",
    "/signout",
    "/_debug/",
)


class BaseAuthBackend(ABC):
    """Abstract Base for Authentication."""
    user_attribute: str = "user"
    password_attribute: str = "password"
    userid_attribute: str = "user_id"
    username_attribute: str = AUTH_USERNAME_ATTRIBUTE
    session_key_property: str = SESSION_KEY
    credentials_required: bool = CREDENTIALS_REQUIRED
    scheme: str = "Bearer"
    session_timeout: int = int(SESSION_TIMEOUT)
    _service: str = None
    _ident: Identity = Identity

    def __init__(
        self,
        user_attribute: str = None,
        userid_attribute: str = None,
        password_attribute: str = None,
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        self._service = self.__class__.__name__
        self._session = None
        # force using of credentials
        self.credentials_required = credentials_required
        self._credentials = None
        self.user_property = SESSION_USER_PROPERTY
        if user_attribute:
            self.user_attribute = user_attribute
        if password_attribute:
            self.password_attribute = password_attribute
        if userid_attribute:
            self.userid_attribute = userid_attribute
        self.username_attribute = AUTH_USERNAME_ATTRIBUTE
        # authentication scheme
        try:
            self.scheme = kwargs["scheme"]
        except KeyError:
            pass
        # configuration Authorization Backends:
        self._authz_backends: list = authorization_backends
        # user and group models
        # getting User and Group Models
        self.user_model: Model = kwargs["user_model"]
        # user mapping
        self.user_mapping = USER_MAPPING
        if not SECRET_KEY:
            fernet_key = fernet.Fernet.generate_key()
            self.secret_key = base64.urlsafe_b64decode(fernet_key)
        else:
            self.secret_key = SECRET_KEY
        # starts the Executor
        self.executor = ThreadPoolExecutor(max_workers=1)

    async def on_startup(self, app: web.Application):
        pass

    async def on_cleanup(self, app: web.Application):
        pass

    async def get_user(self, **search):
        """Getting User Object."""
        try:
            user = await self.user_model.get(**search)
        except Exception as e:
            logging.error(f"Error getting User {search!s}")
            raise UserNotFound(
                f"Error getting User {search!s}: {e!s}"
            ) from e
        # if not exists, return error of missing
        if not user:
            raise UserNotFound(
                f"User {search!s} doesn't exists"
            )
        return user

    async def create_user(self, userdata) -> Identity:
        try:
            usr = self._ident(
                data=userdata
            )
            logging.debug(f'User Created > {usr}')
            return usr
        except Exception as err:
            raise Exception(err) from err

    def get_userdata(self, user = None):
        userdata = {}
        for name, item in self.user_mapping.items():
            if name != self.password_attribute:
                userdata[name] = user[item]
        if AUTH_SESSION_OBJECT:
            return {
                AUTH_SESSION_OBJECT: userdata
            }
        return userdata

    @abstractmethod
    def configure(self, app, router, handler):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""

    async def remember(
            self,
            request: web.Request,
            identity: str,
            userdata: dict,
            user: Identity
        ):
        """
        Saves User Identity into request Object.
        """
        try:
            request[self.session_key_property] = identity
            # saving the user
            request.user = user
            try:
                session = await new_session(request, userdata)
                user.is_authenticated = True # if session, then, user is authenticated.
                session[self.session_key_property] = identity
                session['user'] = session.encode(user)
                request['session'] = session
            except Exception as err:
                raise web.HTTPForbidden(
                    reason=f"Error Creating User Session: {err!s}"
                )
            # to allowing request.user.is_authenticated
        except Exception as err:
            logging.exception(err)

    async def authorization_backends(self, app, handler, request):
        try:
            if isinstance(request.match_info.route, SystemRoute):  # eg. 404
                return True
        except Exception as err:
            logging.error(err)
        # avoid authorization on exclude list
        if request.path in exclude_list:
            return True
        # avoid authorization backend on excluded methods:
        if request.method == hdrs.METH_OPTIONS:
            return True
        try:
            # logic for authorization backends
            for backend in self._authz_backends:
                if backend.check_authorization(request):
                    return True
        except Exception as err:
            logging.error(err)
        return None

    def create_jwt(
        self,
        issuer: str = None,
        expiration: int = None,
        data: dict = None
    ) -> str:
        """Creation of JWT tokens based on basic parameters.
        issuer: for default, urn:Navigator
        expiration: in seconds
        **kwargs: data to put in payload
        """
        if not expiration:
            expiration = self.session_timeout
        if not issuer:
            issuer = "urn:Navigator"
        payload = {
            "exp": datetime.utcnow() + timedelta(seconds=expiration),
            "iat": datetime.utcnow(),
            "iss": issuer,
            **data,
        }
        jwt_token = jwt.encode(
            payload,
            self.secret_key,
            AUTH_JWT_ALGORITHM,
        )
        return jwt_token

    def decode_token(self, request, issuer: str = None):
        jwt_token = None
        tenant = None
        _id = None
        payload = None
        if not issuer:
            issuer = "urn:Navigator"
        if "Authorization" in request.headers:
            try:
                scheme, _id = (
                    request.headers.get(hdrs.AUTHORIZATION).strip().split(" ", 1)
                )
            except ValueError as e:
                raise NavException(
                    "Invalid authorization Header",
                    state=400
                ) from e
            if scheme != self.scheme:
                raise NavException(
                    "Invalid Authorization Scheme",
                    state=400
                )
            try:
                tenant, jwt_token = _id.split(":")
            except Exception:
                # normal Token:
                jwt_token = _id
            # logging.debug(f'Session Token: {jwt_token}')
            try:
                payload = jwt.decode(
                    jwt_token,
                    self.secret_key,
                    algorithms=[AUTH_JWT_ALGORITHM],
                    iss=issuer,
                    leeway=30,
                )
                # logging.info(f"Decoded Token: {payload!s}")
                return [tenant, payload]
            except jwt.exceptions.ExpiredSignatureError as err:
                raise AuthExpired(
                    f"Credentials Expired: {err!s}"
                ) from err
            except jwt.exceptions.InvalidSignatureError as err:
                raise AuthExpired(
                    f"Signature Failed or Expired: {err!s}"
                ) from err
            except jwt.exceptions.DecodeError as err:
                raise FailedAuth(
                    f"Token Decoding Error: {err}"
                ) from err
            except jwt.exceptions.InvalidTokenError as err:
                raise InvalidAuth(
                    f"Invalid authorization token {err!s}"
                ) from err
            except Exception as err:
                raise NavException(
                    err,
                    state=501
                ) from err
        else:
            return [tenant, payload]

    @abstractmethod
    async def check_credentials(self, request):
        """ Authenticate against user credentials (token, user/password)."""

    def threaded_function(self, func: Callable, evt: asyncio.AbstractEventLoop = None, threaded: bool = True):
        """Wraps a Function into an Executor Thread."""
        @wraps(func)
        async def _wrap(*args, loop: asyncio.AbstractEventLoop = None, **kwargs):
            result = None
            if evt is None:
                loop = asyncio.get_event_loop()
            else:
                loop = evt
            try:
                if threaded:
                    fn = partial(func, *args, **kwargs)
                    result = await loop.run_in_executor(
                        self.executor, fn
                    )
                else:
                    result = await func(*args, **kwargs)
                return result
            except Exception as err:
                logging.exception(err)
        return _wrap
