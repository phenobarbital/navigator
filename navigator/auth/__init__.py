"""Navigator Auth.

Navigator Authentication/Authorization system.
"""
from textwrap import dedent
import importlib
import logging
from aiohttp import web
from typing import List, Iterable
from .backends import BaseAuthBackend

# aiohttp session
from .authorizations import *
from navigator.functions import json_response
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth


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
    _user_property: str = "user"
    _required: bool = False

    def __init__(
        self,
        backend: str = "navigator.auth.backends.NoAuth",
        credentials_required: bool = False,
        auth_scheme="Bearer",
        authorization_backends: List = (),
        **kwargs,
    ):
        self._template = dedent(self._template)
        authz_backends = self.get_authorization_backends(authorization_backends)
        args = {
            "credentials_required": credentials_required,
            "scheme": auth_scheme,
            "authorization_backends": authz_backends,
            **kwargs,
        }
        self.backend = self.get_backend(backend, **args)

    def get_backend(self, backend, **kwargs):
        try:
            parts = backend.split(".")
            bkname = parts[-1]
            classpath = ".".join(parts[:-1])
            module = importlib.import_module(classpath, package=bkname)
            obj = getattr(module, bkname)
            return obj(**kwargs)
        except ImportError:
            raise Exception(f"Error loading Auth Backend {backend}")

    async def close(self):
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
            if not user:
                raise web.HTTPUnauthorized(reason="Unauthorized", status=403)
            return json_response(user, state=200)
        except (NavException, UserDoesntExists, InvalidAuth) as err:
            raise web.HTTPUnauthorized(reason=err, status=err.state)
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

    async def get_session(self, request: web.Request) -> web.Response:
        """ return Session Data from user."""
        try:
            dump = await self.backend.get_session(request)
        except NavException as err:
            print("Error HERE: ", err, err.state)
            response = {
                "message": "Session Error",
                "error": err.message,
                "status": err.state,
            }
            return web.json_response(response, status=err.state)
        if dump:
            return json_response(dump)
        else:
            raise web.HTTPForbidden()

    def configure(self, app: web.Application) -> web.Application:
        router = app.router
        # router.add_route("GET", "/login", self.login_page, name="index_login")
        # router.add_route("POST", "/login", self.login, name="login")
        # router.add_route("GET", "/logout", self.logout, name="logout")
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
        router.add_route("GET", "/api/v1/login", self.api_login, name="api_login_get")
        router.add_route("POST", "/api/v1/login", self.api_login, name="api_login_post")
        router.add_route("GET", "/api/v1/logout", self.api_logout, name="api_logout")
        router.add_route(
            "GET",
            "/api/v1/authenticate/{program}",
            self.authenticate,
            name="api_authenticate_program",
        )
        router.add_route(
            "GET", "/api/v1/authenticate", self.authenticate, name="api_authenticate"
        )
        router.add_route(
            "GET",
            "/api/v1/session/{program}",
            self.get_session,
            name="api_session_tenant",
        )
        router.add_route("GET", "/api/v1/session", self.get_session, name="api_session")
        # backed needs initialization (connection to a redis server, etc)
        try:
            self.backend.configure(app, router)
        except Exception as err:
            print(err)
            logging.exception(f"Error on Auth Backend initialization {err!s}")
        # the backend add a middleware to the app
        mdl = app.middlewares
        mdl.append(self.backend.auth_middleware)
        return app
