import logging
import jwt
import importlib
from typing import List, Iterable
from abc import ABC, ABCMeta, abstractmethod
from aiohttp import web, hdrs
from datetime import datetime, timedelta
from asyncdb.utils.models import Model
from cryptography import fernet
import base64
from navigator.conf import (
    NAV_AUTH_USER,
    NAV_AUTH_GROUP,
    JWT_ALGORITHM,
    USER_MAPPING,
    SESSION_TIMEOUT,
    CREDENTIALS_REQUIRED,
    SESSION_KEY,
    SECRET_KEY
)

from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from navigator.functions import json_response
from aiohttp.web_urldispatcher import SystemRoute

JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)

exclude_list = (
    "/static/",
    "/api/v1/login",
    # "/api/v1/logout",
    "/login",
    # "/logout",
    "/signin",
    "/signout",
    "/_debug/",
)


class BaseAuthBackend(ABC):
    """Abstract Base for Authentication."""

    _session = None
    user_model: Model = None
    group_model: Model = None
    user_property: str = "user"
    user_attribute: str = "user"
    password_attribute: str = "password"
    userid_attribute: str = "user_id"
    username_attribute: str = "username"
    user_mapping: dict = {"user_id": "id", "username": "username"}
    session_key_property: str = SESSION_KEY
    credentials_required: bool = False
    scheme: str = "Bearer"
    _authz_backends: List = []
    user_mapping: dict = {}

    def __init__(
        self,
        user_property: str = "user",
        user_attribute: str = "user",
        userid_attribute: str = "user_id",
        username_attribute: str = "username",
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        # force using of credentials
        self.credentials_required = credentials_required
        self.user_property = user_property
        self.user_attribute = user_attribute
        self.userid_attribute = userid_attribute
        self.username_attribute = username_attribute
        # authentication scheme
        self._scheme = kwargs["scheme"]
        # configuration Authorization Backends:
        self._authz_backends = authorization_backends
        # user and group models
        # getting User and Group Models
        self.user_model = self.get_model(NAV_AUTH_USER)
        self.group_model = self.get_model(NAV_AUTH_GROUP)
        self.user_mapping = USER_MAPPING
        if not SECRET_KEY:
            fernet_key = fernet.Fernet.generate_key()
            self.secret_key = base64.urlsafe_b64decode(fernet_key)
        else:
            self.secret_key = SECRET_KEY

    def get_model(self, model, **kwargs):
        try:
            parts = model.split(".")
            name = parts[-1]
            classpath = ".".join(parts[:-1])
            module = importlib.import_module(classpath, package=name)
            obj = getattr(module, name)
            return obj
        except ImportError:
            raise Exception(f"Error loading Auth Model {model}")

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
        return userdata

    def configure(self, app, router):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""
        pass

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
            expiration = JWT_EXP_DELTA_SECONDS
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
                    request.headers.get("Authorization").strip().split(" ", 1)
                )
            except ValueError:
                raise NavException(
                    "Invalid authorization Header",
                    state=400
                )
            if scheme != self._scheme:
                raise NavException(
                    "Invalid Authorization Scheme",
                    state=400
                )
            try:
                tenant, jwt_token = id.split(":")
            except Exception:
                # normal Token:
                jwt_token = id
            try:
                payload = jwt.decode(
                    jwt_token,
                    self.secret_key,
                    algorithms=[JWT_ALGORITHM],
                    iss=issuer,
                    leeway=30,
                )
                logging.debug(f"Decoded Token: {payload!s}")
                return [tenant, payload]
            except (jwt.exceptions.InvalidSignatureError):
                raise NavException("Invalid Signature Error")
            except (jwt.DecodeError) as err:
                raise NavException(f"Token Decoding Error: {err}", state=400)
            except jwt.InvalidTokenError as err:
                print(err)
                raise NavException(f"Invalid authorization token {err!s}")
            except (jwt.ExpiredSignatureError) as err:
                print(err)
                raise NavException(f"Token Expired {err!s}", state=403)
            except Exception as err:
                print(err)
                raise NavException(err, state=501)
        else:
            return [tenant, payload]

    @abstractmethod
    async def check_credentials(self, request):
        """ Authenticate against user credentials (token, user/password)."""
        pass
