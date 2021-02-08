"""Navigator Auth.

Navigator Authentication/Authorization system.
"""
from abc import abstractmethod
from textwrap import dedent
import importlib
import logging
from aiohttp import web
import aioredis
from aiohttp import web
from .backends import BaseAuthHandler
# aiohttp session
from .sessions import CookieSession, RedisSession, MemcacheSession
from .authorizations import authz_hosts
from aiohttp_session import setup as setup_session

from navigator.conf import (
    SECRET_KEY,
    SESSION_URL,
    SESSION_NAME
)

class AuthHandler(object):
    """Authentication Backend for Navigator."""
    _template = """
        <!doctype html>
            <head></head>
            <body>
                <p>{message}</p>
                <form action="/login" method="POST">
                  Login:
                  <input type="text" name="login">
                  Password:
                  <input type="password" name="password">
                  <input type="submit" value="Login">
                </form>
                <a href="/logout">Logout</a>
            </body>
    """
    backend = None
    _session = None
    _user_property: str = 'user'
    _required: bool = False

    def __init__(
            self,
            backend: str = 'navigator.auth.backends.jwt.JWTAuth',
            session_type: str = "cookie",
            name: str = "AIOHTTP_SESSION",
            prefix: str = 'NAVIGATOR_SESSION',
            credentials_required: bool = False,
            user_property: str = 'user',
            auth_scheme='Bearer',
            authorization_backends: tuple = (),
            **kwargs
    ):
        self._template = dedent(self._template)
        self._user_property = user_property
        args = {
            "credentials_required": credentials_required,
            "user_property": self._user_property,
            "scheme": auth_scheme,
            "authorization_backends": authorization_backends,
            **kwargs
        }
        self.backend = self.get_backend(backend, **args)
        if session_type == "cookie":
            self._session = CookieSession(secret=SECRET_KEY, name=name, **args)
        elif session_type == 'redis':
            self._session = RedisSession(name=name, **args)
        elif session_type == 'memcache':
            self._session = MemcacheSession(name=name, **args)
        else:
            raise Exception(f'Unknown Session type {session_type}')

    def get_backend(self, backend, **kwargs):
        try:
            parts = backend.split('.')
            bkname = parts[-1]
            classpath = '.'.join(parts[:-1])
            module = importlib.import_module(classpath, package=bkname)
            obj = getattr(module, bkname)
            return obj(**kwargs)
        except ImportError:
            raise Exception(f"Error loading Auth Backend {backend}")


    async def login(self, request) -> web.Response:
        response = web.HTTPFound("/")
        form = await request.post()
        login = form.get("login")
        password = form.get("password")
        if await self.check_credentials(login, password):
            #await self.create_session(request, login)
            raise response
        else:
            template = self._template.format(
                message="Invalid =username/password= combination"
            )
        raise web.HTTPUnauthorized(text=template, content_type="text/html")

    async def login_page(self, request):
        username = None
        # check if authorized, instead, return to login
        #session = await get_session(request)
        # try:
        #     username = session["username"]
        # except KeyError:
        #     template = self._template.format(message="You need to login")
        # print(template)
        # if username:
        #     template = self._template.format(
        #         message="Hello, {username}!".format(username=username)
        #     )
        # else:
        #     template = self._template.format(message="You need to login")
        # print(template)
        template = self._template.format(message="You need to login")
        return web.Response(text=template, content_type="text/html")

    async def logout(self, request: web.Request) -> web.Response:
        await self._session.forgot_session(request)
        raise web.HTTPSeeOther(location="/")

    async def api_logout(self, request: web.Request) -> web.Response:
        await self._session.forgot_session(request)
        return web.json_response({"message": "logout successful"}, status=200)

    async def api_login(self, request: web.Request) -> web.Response:
        try:
            user = await self.backend.check_credentials(request)
            if not user:
                raise web.HTTPUnauthorized(
                    reason='Unauthorized'
                )
            # first: get user from model
            # if state, save user data in session
            state = await self._session.create_session(request, user=user)
            if state:
                return web.json_response(user, status=200)
            else:
                # failed to create session for User
                raise web.HTTPUnauthorized(
                    reason='Failed to create Session for User'
                )
        except ValueError:
            raise web.HTTPUnauthorized(
                reason='Unauthorized'
            )

    def configure(self, app: web.Application) -> web.Application:
        # configure session:
        session = self._session.configure()
        setup_session(app, session)
        router = app.router
        router.add_route("GET", "/login", self.login_page, name="index_login")
        router.add_route("POST", "/login", self.login, name="login")
        router.add_route("GET", "/logout", self.logout, name="logout")
        router.add_route("GET", "/api/v1/login", self.api_login, name="api_login_get")
        router.add_route("POST", "/api/v1/login", self.api_login, name="api_login_post")
        router.add_route("GET", "/api/v1/logout", self.api_logout, name="api_logout")
        # backed needs initialization (connection to a redis server, etc)
        try:
            self.backend.configure()
        except Exception as err:
            print(err)
            logging.exception(f'Error on Auth Backend initialization {err!s}')
        # the backend add a middleware to the app
        mdl = app.middlewares
        mdl.append(self.backend.auth_middleware)
        return app
