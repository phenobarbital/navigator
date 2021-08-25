"""Navigator Auth.

Navigator Authentication/Authorization system.

AuthHandler is the Authentication/Authorization system for NAV,
Supporting:
 * multiple authentication backends
 * authorization exceptions via middlewares
 * Session Support (in the top of aiohttp-session)
"""
from textwrap import dedent
import importlib
import logging
from aiohttp import web
from typing import List, Iterable
from .authorizations import *
from navigator.functions import json_response
from navigator.auth.session import (
    CookieSession,
    RedisSession,
    MemcacheSession
)
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from navigator.conf import (
    AUTHORIZATION_BACKENDS,
    CREDENTIALS_REQUIRED,
    SESSION_TIMEOUT,
    AUTHENTICATION_BACKENDS,
    AUTHORIZATION_MIDDLEWARES,
    DOMAIN,
    SESSION_NAME,
    SESSION_STORAGE,
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM
)
from aiohttp_session import get_session, new_session

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
    backends: List = None
    _session = None
    _user_property: str = "user"
    _required: bool = False
    _middlewares: Iterable = []

    def __init__(
        self,
        auth_scheme="Bearer",
        **kwargs,
    ):
        self._template = dedent(self._template)
        authz_backends = self.get_authorization_backends(AUTHORIZATION_BACKENDS)
        args = {
            "credentials_required": CREDENTIALS_REQUIRED,
            "scheme": auth_scheme,
            "authorization_backends": authz_backends,
            **kwargs,
        }
        # get the authentication backends (all of the list)
        self.backends = self.get_backends(**args)
        self._middlewares = self.get_authorization_middlewares(
            AUTHORIZATION_MIDDLEWARES
        )
        # Session Support:
        # getting Session Object:
        if SESSION_STORAGE == "cookie":
            self._session = CookieSession(
                name=SESSION_NAME,
                secret=SECRET_KEY
            )
        elif SESSION_STORAGE == "redis":
            self._session = RedisSession(
                name=SESSION_NAME
            )
        elif SESSION_STORAGE == "memcache":
            self._session = MemcacheSession(
                name=SESSION_NAME
            )
        else:
            raise NavException(
                f"Unknown Session type {session_type}"
            )

    def get_backends(self, **kwargs):
        backends = []
        for backend in AUTHENTICATION_BACKENDS:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                backends.append(obj(**kwargs))
            except ImportError:
                raise Exception(f"Error loading Auth Backend {backend}")
        return backends

    async def on_cleanup(self, app):
        """
        Cleanup the processes
        """
        pass

    def get_authorization_backends(self, backends: Iterable) -> tuple:
        b = []
        for backend in backends:
            # TODO: more automagic logic
            if backend == "hosts":
                b.append(authz_hosts())
            elif backend == "allow_hosts":
                b.append(authz_allow_hosts())
        return b

    def get_authorization_middlewares(self, backends: Iterable) -> tuple:
        b = []
        for backend in backends:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                b.append(obj)
            except ImportError:
                raise Exception(
                    f"Error loading Authz Middleware {backend}"
                )
        return b


    # async def login(self, request) -> web.Response:
    #     response = web.HTTPFound("/")
    #     form = await request.post()
    #     login = form.get("login")
    #     password = form.get("password")
    #     if user := await self.check_credentials(login, password):
    #         # if state, save user data in session
    #         state = await self._session.create_session(request, user=user)
    #         raise response
    #     else:
    #         template = self._template.format(
    #             message="Invalid =username/password= combination"
    #         )
    #     raise web.HTTPUnauthorized(text=template, content_type="text/html")
    #
    # async def login_page(self, request):
    #     username = None
    #     # check if authorized, instead, return to login
    #     #session = await get_session(request)
    #     # try:
    #     #     username = session["username"]
    #     # except KeyError:
    #     #     template = self._template.format(message="You need to login")
    #     # print(template)
    #     # if username:
    #     #     template = self._template.format(
    #     #         message="Hello, {username}!".format(username=username)
    #     #     )
    #     # else:
    #     #     template = self._template.format(message="You need to login")
    #     # print(template)
    #     template = self._template.format(message="You need to login")
    #     return web.Response(text=template, content_type="text/html")
    #
    # async def logout(self, request: web.Request) -> web.Response:
    #     await self._session.forgot_session(request)
    #     raise web.HTTPSeeOther(location="/")

    async def api_logout(self, request: web.Request) -> web.Response:
        await self.backend.forgot_session(request)
        return web.json_response({"message": "logout successful"}, status=200)

    async def api_login(self, request: web.Request) -> web.Response:
        try:
            user = await self.backend.check_credentials(request)
            print('USER: ', user)
            if not user:
                raise web.HTTPUnauthorized(
                    reason="Unauthorized",
                    status=403
                )
            return json_response(user, state=200)
        except (NavException, UserDoesntExists, InvalidAuth) as err:
            raise web.HTTPUnauthorized(
                reason=err,
                status=err.state
            )
        except ValueError:
            raise web.HTTPUnauthorized(reason="Unauthorized")
        except Exception as err:
            print(err)
            raise web.HTTPUnauthorized(reason=err, status=403)

    async def authenticate(self, request: web.Request) -> web.Response:
        """ Authentication method to refresh credentials for Registration."""
        auth = await self.backend.check_authorization(request)
        if not auth:
            raise web.HTTPUnauthorized(reason="User not Authorized")

    # Session Methods:
    async def forgot_session(self, request: web.Request):
        await self._session.forgot(request)

    async def create_session(self, request: web.Request):
        return await self._session.create(request)

    async def get_session(self, request: web.Request) -> web.Response:
        """ Get user data from session."""
        try:
            session = await self._session.get_session(request)
        except NavException as err:
            print("Error HERE: ", err, err.state)
            response = {
                "message": "Session Error",
                "error": err.message,
                "status": err.state,
            }
            return web.json_response(response, status=err.state)
        if not session:
            try:
                session = await get_session(request)
            except Exception as e:
                print(e)
                # always return a null session for user:
                session = await new_session(request)
        return session

    def configure(self, app: web.Application) -> web.Application:
        router = app.router
        router.add_route(
            "GET",
            "/api/v1/login/{program}",
            self.api_login,
            name="api_login_get_tenant",
        )
        router.add_route(
            "POST",
            "/api/v1/login/{program}",
            self.api_login,
            name="api_login_post_tenant",
        )
        router.add_route(
            "GET",
            "/api/v1/login",
            self.api_login,
            name="api_login"
        )
        router.add_route(
            "POST",
            "/api/v1/login",
            self.api_login,
            name="api_login_post"
        )
        router.add_route(
            "GET",
            "/api/v1/logout",
            self.api_logout,
            name="api_logout"
        )
        # new route: authenticate against a especific program:
        router.add_route(
            "GET",
            "/api/v1/authenticate/{program}",
            self.authenticate,
            name="api_authenticate_program",
        )
        # refresh or reconfigure authentication
        router.add_route(
            "GET", "/api/v1/authenticate",
            self.authenticate,
            name="api_authenticate"
        )
        # get the session information for a program (only)
        router.add_route(
            "GET",
            "/api/v1/session/{program}",
            self.get_session,
            name="api_session_tenant",
        )
        # get all user information
        router.add_route(
            "GET",
            "/api/v1/session",
            self.get_session,
            name="api_session"
        )
        # if a backend needs initialization
        # (connection to a redis server, etc)
        try:
            for backend in self.backends:
                backend.configure(app, router)
        except Exception as err:
            print(err)
            logging.exception(
                f"Error on Auth Backend initialization {err!s}"
            )
        # the backend add a middleware to the app
        mdl = app.middlewares
        # configuring Session Object
        self._session.configure_session(app)
        # add the middleware for Basic Authentication
        # mdl.append(self.backend.auth_middleware)
        # at last: add other middleware support
        if self._middlewares:
            mdl.append(self._middlewares)
        # print(mdl)
        return app
