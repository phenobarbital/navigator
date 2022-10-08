#!/usr/bin/env python3
import asyncio
import importlib
import inspect
from pathlib import Path
from collections.abc import Callable
from aiohttp import web, web_response
from aiohttp.abc import AbstractView
from asyncdb.exceptions import ProviderError, DriverError
from navigator.applications.base import BaseHandler
from navigator.connections import PostgresPool
from navigator.middlewares.error import error_middleware
from navigator.responses import JSONResponse
## Auth Extension
from navigator.auth import AuthHandler
from navigator.exceptions import (
    ConfigError
)
from .base import BaseHandler
from .conf import (
    APP_DIR
)


class AppHandler(BaseHandler):
    """
    AppHandler.

    Main Class for registration principal (Main) aiohttp App.
    can register Callbacks, Signals, Route Initialization, etc
    """
    _middleware: list = []
    auto_doc: bool = False
    enable_auth: bool = False
    enable_db: bool = False
    enable_static: bool = False
    staticdir: str = None
    enable_pgpool: bool = False

    def __init__(
        self,
        context: dict,
        app_name: str = None,
        evt: asyncio.AbstractEventLoop = None
    ) -> None:
        super(
            AppHandler, self
        ).__init__(
            context=context,
            app_name=app_name,
            evt=evt
        )
        if self.enable_pgpool is True:
            try:
            # enable a pool-based database connection:
                pool = PostgresPool(
                    name='Program',
                    startup=self.app_startup
                )
                pool.configure(self.app, register='database') # pylint: disable=E1123
            except (ProviderError, DriverError) as ex:
                raise web.HTTPServerError(
                    reason=f"Error creating Database connection: {ex}"
                )

    def CreateApp(self) -> web.Application:
        app = super(AppHandler, self).CreateApp()
        # Setup Authentication (if enabled):
        if self.enable_auth is True:
            self._auth = AuthHandler()
            # configuring authentication endpoints
            self._auth.setup(
                app=app,
                handler=self
            )
        # add the other middlewares:
        try:
            for middleware in self._middleware:
                app.middlewares.append(middleware)
        except (ValueError, TypeError):
            pass
        # add the error middleware at end:
        app.middlewares.append(error_middleware)
        return app

    def configure(self) -> None:
        """
        configure.
            making configuration of routes
        """
        if self.enable_static is True:
            # adding static directory.
            self.app.router.add_static(
                "/static/",
                path=self.staticdir,
                name='static',
                append_version=True,
                show_index=True,
                follow_symlinks=True
            )

    def setup_docs(self) -> None:
        """
        setup_docs.
        description: define CORS configuration
        """
        # Configure CORS, swagger and documentation from all routes.
        if self.auto_doc is True:
            for route in list(self.app.router.routes()):
                fn = route.handler
                signature = inspect.signature(fn)
                doc = fn.__doc__
                if doc is None and "OPTIONS" not in route.method:
                    # TODO: making more efficiently
                    fnName = fn.__name__
                    if fnName in ["_handle", "channel_handler", "WebSocket"]:
                        continue
                    if signature.return_annotation:
                        response = str(signature.return_annotation)
                    else:
                        response = web_response.Response
                    doc = """
                    summary: {fnName}
                    description: Auto-Doc for Function {fnName}
                    tags:
                    - Utilities
                    produces:
                    - application/json
                    responses:
                        "200":
                            description: Successful operation
                            content:
                                {response}
                        "404":
                            description: Not found
                        "405":
                            description: invalid HTTP Method
                    """.format(
                        fnName=fnName, response=response
                    )
                    try:
                        fn.__doc__ = doc
                    except (AttributeError, ValueError):
                        pass

    def setup_cors(self, cors):
        for route in list(self.app.router.routes()):
            try:
                if inspect.isclass(route.handler) and issubclass(
                    route.handler, AbstractView
                ):
                    cors.add(route, webview=True)
                else:
                    cors.add(route)
            except (TypeError, ValueError):
                pass


class AppConfig(AppHandler):
    """
    AppConfig.

    Class for Configuration of aiohttp SubApps
    """
    path: Path = None
    _middleware: list = []
    domain: str = ""
    version: str = '0.0.1'
    description: str = ''
    template: str = "templates"

    def __init__(
        self,
        *args,
        **kwargs
    ):
        self._name = type(self).__name__
        self._listener: Callable = None
        super(AppConfig, self).__init__(*args, **kwargs)
        self.path = APP_DIR.joinpath(self._name)
        # set the setup_routes
        self.setup_routes()
        # authorization
        self.app.router.add_get(
            '/authorize', self.app_authorization
        )

    def setup_routes(self):
        """Setup Routes (URLS) pointing to paths on AppConfig."""
        # set the urls
        # TODO: automatic module loader
        try:
            cls = importlib.import_module(
                "{}.{}".format("apps.{}".format(self._name), "urls"), package="apps" # pylint: disable=C0209
            )
            routes = getattr(cls, "urls")
        except ModuleNotFoundError:
            return False
        except ImportError as err:
            self.logger.exception(err, stack_info=True)
            return False
        for route in routes:
            # print(route, route.method)
            if inspect.isclass(route.handler) and issubclass(
                route.handler, AbstractView
            ):
                if route.method is None:
                    r = self.app.router.add_view(
                        route.url, route.handler, name=route.name
                    )
                    self.cors.add(r, webview=True)
                elif not route.method:
                    r = self.app.router.add_view(
                        route.url, route.handler, name=route.name
                    )
                elif route.method == "*":
                    r = self.app.router.add_route(
                        "*", route.url, route.handler, name=route.name
                    )
                else:
                    if route.method == "get":
                        r = self.app.router.add_get(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "post":
                        r = self.app.router.add_post(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "delete":
                        r = self.app.router.add_delete(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "patch":
                        r = self.app.router.add_patch(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "put":
                        r = self.app.router.add_put(
                            route.url, route.handler, name=route.name
                        )
                    else:
                        raise Exception(
                            f"Unsupported Method for Route {route.method}, program: {self._name}"
                        )
                    self.cors.add(r, webview=True)
            elif inspect.isclass(route.handler):
                r = self.app.router.add_view(route.url, route.handler, name=route.name)
                self.cors.add(r, webview=True)
            else:
                if not route.method:
                    r = self.app.router.add_route(
                        "*", route.url, route.handler, name=route.name
                    )
                else:
                    if route.method == "get":
                        r = self.app.router.add_get(
                            route.url, route.handler, name=route.name, allow_head=False
                        )
                    elif route.method == "post":
                        r = self.app.router.add_post(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "delete":
                        r = self.app.router.add_delete(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "patch":
                        r = self.app.router.add_patch(
                            route.url, route.handler, name=route.name
                        )
                    elif route.method == "put":
                        r = self.app.router.add_put(
                            route.url, route.handler, name=route.name
                        )
                    else:
                        raise ConfigError(
                            f"Unsupported Method for Route {route.method}, program: {self._name}"
                        )
                    self.cors.add(r)

    async def app_authorization(self, request: web.Request) -> web.Response:
        """app_authorization.

        We can extend this function to allow/deny access to certain applications.
        Args:
            request (web.Request): aiohttp web Request.

        Returns:
            web.Response:
        """
        try:
            program = request.match_info['program']
        except (AttributeError, KeyError):
            program = self.__class__.__name__
        authorization = {
            "status": "Tenant Authorized",
            "program": program
        }
        return JSONResponse(authorization, status=200)

    async def on_startup(self, app: web.Application):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """
        await super(AppConfig, self).on_startup(app)
        if self.enable_pgpool is True:
            db = app['Main']['database']
            app['database'] = db

class BaseApp(AppConfig):
    """BaseApp.

    This App making responses by default when app doesn't exists but is added to installed (fallback App.)
    """
    __version__ = '0.0.1'
    _name: str = None
    app_description = """NAVIGATOR"""
    enable_pgpool: bool = True
