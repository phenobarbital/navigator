"""Navigator Auth.

Navigator Authentication/Authorization system.

AuthHandler is the Authentication/Authorization system for NAV,
Supporting:
 * multiple authentication backends
 * authorization exceptions via middlewares
 * Session Support (on top of navigator-session)
"""
from textwrap import dedent
import importlib
import logging
from typing import (
    Optional
)
from collections.abc import Iterable
from aiohttp import web
from navigator_session import (
    RedisStorage, SESSION_KEY
)
from navigator.exceptions import (
    NavException,
    UserNotFound,
    InvalidAuth,
    FailedAuth,
    ConfigError
)
from navigator.conf import (
    CREDENTIALS_REQUIRED,
    AUTHENTICATION_BACKENDS,
    AUTHORIZATION_BACKENDS,
    AUTHORIZATION_MIDDLEWARES,
    AUTH_USER_MODEL
)
from navigator.extensions import BaseExtension
from navigator.responses import JSONResponse
from .authorizations import *


class AuthHandler(BaseExtension):
    """Authentication Backend for Navigator."""
    name: str = 'auth'
    _template: str = """
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
    def __init__(
            self,
            app_name: str = None,
            **kwargs
        ) -> None:
        super(AuthHandler, self).__init__(
            app_name=app_name,
            **kwargs
        )
        self.backends: dict = {}
        self._session = None
        self._template = dedent(self._template)
        authz_backends = self.get_authorization_backends(
            AUTHORIZATION_BACKENDS
        )
        if 'scheme' in kwargs:
            self.auth_scheme = kwargs['scheme']
        else:
            self.auth_scheme = 'Bearer'
        # Get User Model:
        try:
            user_model = self.get_usermodel(AUTH_USER_MODEL)
        except Exception as ex:
            raise ConfigError(
                f"Error Getting Auth User Model: {ex}"
            ) from ex
        args = {
            "credentials_required": CREDENTIALS_REQUIRED,
            "scheme": self.auth_scheme,
            "authorization_backends": authz_backends,
            "user_model": user_model,
            **kwargs,
        }
        # get the authentication backends (all of the list)
        self.backends = self.get_backends(**args)
        self._middlewares = self.get_authorization_middlewares(
            AUTHORIZATION_MIDDLEWARES
        )
        # TODO: Session Support with parametrization (other backends):
        self._session = RedisStorage()
        # Signal for any startup method on application.
        self.on_startup = self.auth_startup

    def get_backends(self, **kwargs):
        backends = {}
        for backend in AUTHENTICATION_BACKENDS:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                logging.debug(f'Loading Auth Backend {bkname}')
                backends[bkname] = obj(**kwargs)
            except ImportError as ex:
                raise ConfigError(
                    f"Error loading Auth Backend {backend}: {ex}"
                ) from ex
        return backends

    def get_usermodel(self, model: str):
        try:
            parts = model.split(".")
            name = parts[-1]
            classpath = ".".join(parts[:-1])
            module = importlib.import_module(classpath, package=name)
            obj = getattr(module, name)
            return obj
        except ImportError as ex:
            raise Exception(
                f"Error loading Auth User Model {model}: {ex}"
            ) from ex

    async def auth_startup(self, app):
        """
        Some Authentication backends need to call an Startup.
        """
        for name, backend in self.backends.items():
            try:
                await backend.on_startup(app)
            except Exception as err:
                logging.exception(
                    f"Error on Startup Auth Backend {name} init: {err!s}"
                )
                raise NavException(
                    f"Error on Startup Auth Backend {name} init: {err!s}"
                ) from err

    async def on_cleanup(self, app):
        """
        Cleanup the processes
        """
        for name, backend in self.backends.items():
            try:
                await backend.on_cleanup(app)
            except Exception as err:
                print(err)
                logging.exception(
                    f"Error on Cleanup Auth Backend {name} init: {err!s}"
                )
                raise NavException(
                    f"Error on Cleanup Auth Backend {name} init: {err!s}"
                ) from err

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
        b = tuple()
        for backend in backends:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                b.append(obj)
            except ImportError as ex:
                raise Exception(
                    f"Error loading Authz Middleware {backend}: {ex}"
                ) from ex
        return b

    async def api_logout(self, request: web.Request) -> web.Response:
        """Logout.
        API-based Logout.
        """
        try:
            await self._session.forgot(request)
            return web.json_response(
                {
                    "message": "Logout successful",
                    "state": 202
                },
                status=202
            )
        except Exception as err:
            print(err)
            raise web.HTTPUnauthorized(
                reason=f"Logout Error {err!s}"
            )

    async def api_login(self, request: web.Request) -> web.Response:
        """Login.

        API based login.
        """
        # first: getting header for an existing backend
        method = request.headers.get('X-Auth-Method')
        if method:
            try:
                backend = self.backends[method]
            except KeyError as ex:
                raise web.HTTPUnauthorized(
                    reason=f"Unacceptable Auth Method {method}",
                    content_type="application/json"
                ) from ex
            try:
                userdata = await backend.authenticate(request)
                if not userdata:
                    raise web.HTTPForbidden(
                        reason='User was not authenticated'
                    )
            except FailedAuth as err:
                raise web.HTTPForbidden(
                    reason=f"{err!s}"
                )
            except InvalidAuth as err:
                logging.exception(err)
                raise web.HTTPForbidden(
                    reason=f"{err!s}"
                )
            except UserNotFound as err:
                raise web.HTTPForbidden(
                    reason="User Doesn't exists: {err!s}"
                )
            except Exception as err:
                raise web.HTTPClientError(
                    reason=f"{err!s}"
                )
            return JSONResponse(userdata, status=200)
        else:
            # second: if no backend declared, will iterate over all backends
            userdata = None
            for _, backend in self.backends.items():
                try:
                    # check credentials for all backends
                    userdata = await backend.authenticate(request)
                    if userdata:
                        break
                except (
                    NavException,
                    UserNotFound,
                    InvalidAuth,
                    FailedAuth
                ) as err:
                    continue
                except Exception as err:
                    raise web.HTTPClientError(
                        reason=err
                    ) from err
            # if not userdata, then raise an not Authorized
            if not userdata:
                raise web.HTTPForbidden(
                    reason="Login Failure in all Auth Methods."
                )
            else:
                # at now: create the user-session
                try:
                    await self._session.new_session(request, userdata)
                except Exception as err:
                    raise web.HTTPUnauthorized(
                        reason=f"Error Creating User Session: {err!s}"
                    ) from err
                return JSONResponse(userdata, status=200)

    # Session Methods:
    async def forgot_session(self, request: web.Request):
        await self._session.forgot(request)

    async def create_session(self, request: web.Request, data: Iterable):
        return await self._session.new_session(request, data)

    async def get_session(self, request: web.Request) -> web.Response:
        """ Get user data from session."""
        session = None
        try:
            session = await self._session.get_session(request)
        except NavException as err:
            response = {
                "message": "Session Error",
                "error": err.message,
                "status": err.state,
            }
            return JSONResponse(response, status=err.state)
        except Exception as err:
            raise web.HTTPClientError(
                reason=err
            ) from err
        if not session:
            try:
                session = await self._session.get_session(request)
            except Exception: # pylint: disable=W0703
                # always return a null session for user:
                session = await self._session.new_session(request, {})
        userdata = dict(session)
        try:
            del userdata['user']
        except KeyError:
            pass
        return JSONResponse(userdata, status=200)

    def setup(
            self,
            app: web.Application,
            handler
        ) -> web.Application:
        ## calling parent Setup:
        super(AuthHandler, self).setup(app)
        # cleanup operations over authentication backends
        app.on_cleanup.append(
            self.on_cleanup
        )
        router = app.router
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
            "/api/v1/user/session",
            self.get_session,
            name="api_session"
        )
        # configuring Session Object
        self._session.configure_session(app)
        # the backend add a middleware to the app
        mdl = app.middlewares
        # if authentication backend needs initialization
        for name, backend in self.backends.items():
            try:
                backend.configure(app, router, handler)
                if hasattr(backend, "auth_middleware"):
                    # add the middleware for Basic Authentication
                    mdl.append(backend.auth_middleware)
            except Exception as err:
                print(err)
                logging.exception(
                    f"Error on Auth Backend {name} init: {err!s}"
                )
                raise ConfigError(
                    f"Error on Auth Backend {name} init: {err!s}"
                ) from err
        # # at last: add other middleware support
        # if self._middlewares:
        #     for mid in self._middlewares:
        #         mdl.append(mid)
        return app

    async def get_auth(
        self,
        request: web.Request
    ) -> str:
        """
        Get the current User ID from Request
        """
        return request.get(SESSION_KEY, None)

    async def get_userdata(
        self,
        request: web.Request
    ) -> str:
        """
        Get the current User ID from Request
        """
        data = request.get(self.user_property, None)
        if data:
            return data
        else:
            raise web.HTTPForbidden(
                reason="Auth: User Data is missing on Request."
            )
