import logging
import jwt
import importlib
from typing import List, Iterable
from abc import ABC, ABCMeta, abstractmethod
from aiohttp import web, hdrs
from datetime import datetime, timedelta
from asyncdb.utils.models import Model
from aiohttp_session import setup as setup_session
from navigator.conf import (
    DOMAIN,
    NAV_AUTH_USER,
    NAV_AUTH_GROUP,
    SESSION_NAME,
    SESSION_STORAGE,
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM,
    USER_MAPPING
)
from navigator.auth.session import CookieSession, RedisSession, MemcacheSession
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = JWT_ALGORITHM
JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)

exclude_list = (
    '/api/v1/login',
    '/api/v1/logout',
    '/login',
    '/logout'
)


class BaseAuthBackend(ABC):
    """Abstract Base for Authentication."""
    _session = None
    user_model: Model = None
    group_model: Model = None
    user_property: str = 'user'
    user_attribute: str = 'user'
    userid_attribute: str = 'user_id'
    username_attribute: str = 'username'
    user_mapping: dict = {'user_id': 'id', 'username': 'username'}
    credentials_required: bool = False
    _scheme: str = 'Bearer'
    _authz_backends: List = []
    user_mapping: dict = {}

    def __init__(
            self,
            user_property: str = 'user',
            user_attribute: str = 'user',
            userid_attribute: str = 'user_id',
            username_attribute: str = 'username',
            credentials_required: bool = False,
            authorization_backends: tuple = (),
            session_type: str = 'cookie',
            **kwargs
    ):
        # force using of credentials
        self.credentials_required = credentials_required
        self.user_property = user_property
        self.user_attribute = user_attribute
        self.userid_attribute = userid_attribute
        self.username_attribute = username_attribute
        # authentication scheme
        self._scheme = kwargs['scheme']
        # configuration Authorization Backends:
        self._authz_backends = authorization_backends
        # user and group models
        # getting User and Group Models
        self.user_model = self.get_model(NAV_AUTH_USER)
        self.group_model = self.get_model(NAV_AUTH_GROUP)
        self.user_mapping = USER_MAPPING
        # getting Session Object:
        args = {
            "user_property": user_property,
            "user_attribute": user_attribute,
            "username_attribute": username_attribute,
            **kwargs
        }
        if SESSION_STORAGE == "cookie":
            self._session = CookieSession(secret=SECRET_KEY, name=SESSION_NAME, **args)
        elif SESSION_STORAGE == 'redis':
            self._session = RedisSession(name=SESSION_NAME, **args)
        elif SESSION_STORAGE == 'memcache':
            self._session = MemcacheSession(name=SESSION_NAME, **args)
        else:
            raise Exception(f'Unknown Session type {session_type}')

    def get_model(self, model, **kwargs):
        try:
            parts = model.split('.')
            name = parts[-1]
            classpath = '.'.join(parts[:-1])
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
            logging.error(f'Error getting User {search!s}')
            raise Exception(err)
        # if not exists, return error of missing
        if not user:
            raise UserDoesntExists(f'User doesnt exists')
        return user

    def configure(self, app, router):
        """ Base configuration for Auth Backends, need to be extended
        to create Session Object."""
        try:
            # configuring Session Object
            self._session.configure()
            # configure the aiohttp session
            setup_session(app, self._session.session)
        except Exception as err:
            print(err)
            raise Exception(err)

    async def authorization_backends(self, app, handler, request):
        # avoid authorization backend on excluded methods:
        if request.path in exclude_list:
            return handler(request)
        if request.method == hdrs.METH_OPTIONS:
            return handler(request)
        # logic for authorization backends
        for backend in self._authz_backends:
            if await backend.check_authorization(request):
                return handler(request)
        return None

    def create_jwt(self, audience: str = None, issuer: str = None, expiration: int = None, data: dict = None) -> str:
        """ Creation of JWT tokens based on basic parameters.
        audience: if not set, using current domain name
        issuer: for default, urn:Navigator
        expiration: in seconds
        **kwargs: data to put in payload
        """
        if not expiration:
            expiration = JWT_EXP_DELTA_SECONDS
        if not issuer:
            issuer = 'urn:Navigator'
        if not audience:
            audience = DOMAIN
        payload = {
            'exp': datetime.utcnow() + timedelta(seconds=expiration),
            "iat": datetime.utcnow(),
            "nbf": datetime.utcnow(),
            "iss": issuer,
            "aud": audience,
            **data
        }
        jwt_token = jwt.encode(
            payload,
            JWT_SECRET,
            JWT_ALGORITHM,
        )
        return jwt_token

    async def forgot_session(self, request: web.Request):
        await self._session.forgot_session(request)

    @abstractmethod
    async def check_credentials(self, request):
        """ Authenticate against user credentials (token, user/password)."""
        pass

    @abstractmethod
    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        pass

    @abstractmethod
    async def get_session(self, request):
        """ Get user data from session."""
        pass

    @abstractmethod
    async def auth_middleware(self, app, handler):
        """ Base Middleware for Authentication Backend."""
        async def middleware(request):
            return await handler(request)
        return middleware
