import logging
import jwt
import importlib
from typing import List, Dict
from abc import ABC, abstractmethod
from aiohttp import web, hdrs
from datetime import datetime, timedelta
from asyncdb.models import Model
from cryptography import fernet
import base64
from navigator.conf import (
    AUTH_USER_MODEL,
    AUTH_GROUP_MODEL,
    AUTH_SESSION_OBJECT,
    AUTH_USERNAME_ATTRIBUTE,
    JWT_ALGORITHM,
    USER_MAPPING,
    SESSION_TIMEOUT,
    CREDENTIALS_REQUIRED,
    SESSION_KEY,
    SECRET_KEY,
    SESSION_USER_PROPERTY
)
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth,
    FailedAuth,
    AuthExpired
)
from aiohttp.web_urldispatcher import SystemRoute
from navigator.auth.sessions import get_session, new_session

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
    userid_attribute: str = "user_id"
    username_attribute: str = AUTH_USERNAME_ATTRIBUTE
    session_key_property: str = SESSION_KEY
    credentials_required: bool = CREDENTIALS_REQUIRED
    scheme: str = "Bearer"
    session_timeout: int = int(SESSION_TIMEOUT)

    def __init__(
        self,
        user_attribute: str = "user",
        userid_attribute: str = "user_id",
        password_attribute: str = "password",
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        self._session = None
        # force using of credentials
        self.credentials_required = credentials_required
        self.user_property = SESSION_USER_PROPERTY
        self.user_attribute = user_attribute
        self.password_attribute = password_attribute
        self.userid_attribute = userid_attribute
        self.username_attribute = AUTH_USERNAME_ATTRIBUTE
        # authentication scheme
        try:
            self.scheme = kwargs["scheme"]
        except KeyError:
            pass
        # configuration Authorization Backends:
        self._authz_backends: List = authorization_backends
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

    async def on_startup(self, app: web.Application):
        pass
    
    async def on_cleanup(self, app: web.Application):
        pass

    async def get_user(self, **search):
        """Getting User Object."""
        # TODO: getting Groups based on User
        try:
            user = await self.user_model.get(**search)
        except Exception as err:
            logging.error(f"Error getting User {search!s}")
            raise Exception(err)
        # if not exists, return error of missing
        if not user:
            raise UserDoesntExists(f"User doesnt exists")
        return user

    def get_userdata(self, user):
        userdata = {}
        for name, item in self.user_mapping.items():
            if name != self.password_attribute:
                userdata[name] = user[item]
        if AUTH_SESSION_OBJECT:
            return {
                AUTH_SESSION_OBJECT: userdata
            }
        return userdata

    def configure(self, app, router, handler):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""
        pass

    async def remember(
            self,
            request: web.Request,
            identity: str,
            userdata: Dict,
            user: Identity
        ):
        """
        Saves User Identity into request Object.
        """
        try:
            request[self.session_key_property] = identity
            # request[self.user_property] = userdata
            # saving the user
            request.user = user
            # Session:
            try:
                session = await new_session(request, userdata)
                user.is_authenticated = True # if session, then, user is authenticated.
                # which Auth Method:
                user.auth_method = self.__class__.__name__
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
        if isinstance(request.match_info.route, SystemRoute):  # eg. 404
            return await handler(request)
        # avoid authorization on exclude list
        if request.path in exclude_list:
            return handler(request)
        # avoid authorization backend on excluded methods:
        if request.method == hdrs.METH_OPTIONS:
            return handler(request)
        # logic for authorization backends
        for backend in self._authz_backends:
            if await backend.check_authorization(request):
                return handler(request)
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
            JWT_ALGORITHM,
        )
        return jwt_token

    def decode_token(self, request, issuer: str = None):
        jwt_token = None
        tenant = None
        id = None
        payload = None
        if not issuer:
            issuer = "urn:Navigator"
        if "Authorization" in request.headers:
            try:
                scheme, id = (
                    request.headers.get(hdrs.AUTHORIZATION).strip().split(" ", 1)
                )
            except ValueError:
                raise NavException(
                    "Invalid authorization Header",
                    state=400
                )
            if scheme != self.scheme:
                raise NavException(
                    "Invalid Authorization Scheme",
                    state=400
                )
            try:
                tenant, jwt_token = id.split(":")
            except Exception:
                # normal Token:
                jwt_token = id
            logging.debug(f'Session Token: {jwt_token}')
            try:
                payload = jwt.decode(
                    jwt_token,
                    self.secret_key,
                    algorithms=[JWT_ALGORITHM],
                    iss=issuer,
                    leeway=30,
                )
                logging.info(f"Decoded Token: {payload!s}")
                return [tenant, payload]
            except jwt.exceptions.ExpiredSignatureError as err:
                raise AuthExpired(f"Credentials Expired: {err!s}")
            except jwt.exceptions.InvalidSignatureError as err:
                raise AuthExpired(f"Signature Failed or Expired: {err!s}")
            except jwt.exceptions.DecodeError as err:
                raise FailedAuth(f"Token Decoding Error: {err}")
            except jwt.exceptions.InvalidTokenError as err:
                raise InvalidAuth(f"Invalid authorization token {err!s}")
            except Exception as err:
                raise NavException(err, state=501)
        else:
            return [tenant, payload]

    @abstractmethod
    async def check_credentials(self, request):
        """ Authenticate against user credentials (token, user/password)."""
        pass
