#!/usr/bin/env python3
import asyncio
from abc import ABC
import importlib
import inspect
from pathlib import Path
from collections.abc import Callable
import aiohttp_cors
from aiohttp import web, web_response
from aiohttp.abc import AbstractView
from asyncdb.exceptions import ProviderError, DriverError
from navconfig.logging import logging
from navigator.conf import (
    APP_NAME,
    APP_DIR,
    DEBUG,
    STATIC_DIR,
    default_dsn
)
from navigator.connections import PostgresPool
# make a home and a ping class
from navigator.resources import ping
from navigator.functions import cPrint
from navigator.utils.functions import get_logger
from navigator.responses import JSONResponse
## Auth Extension
from navigator.auth import AuthHandler
from navigator.exceptions import (
    ConfigError
)
# get the default Router system.
from .routes import Router


#######################
##
## APPS CONFIGURATION
##
#######################
def app_startup(app_list: list, app: web.Application, context: dict, **kwargs: dict):
    """ Initialize all Apps in the existing Installation."""
    for apps in app_list:
        obj = None
        app_name, app_class = apps # splitting the tuple
        try:
            instance_app = None
            name = app_name.split(".")[1]
            if app_class is not None:
                obj = getattr(app_class, name)
                instance_app = obj(context=context, app_name=name, **kwargs)
                domain = getattr(instance_app, "domain", None)
            else:
                ## TODO: making a default App configurable.
                instance_app = BaseApp(context=context, app_name=name, **kwargs)
                instance_app.__class__.__name__ = name
                domain = None
            sub_app = instance_app.App
            if domain:
                app.add_domain(domain, sub_app)
                # TODO: adding as sub-app as well
            else:
                app.add_subapp(f"/{name}/", sub_app)
            # TODO: build automatic documentation
            try:
                # can I add Main to subApp?
                sub_app['Main'] = app
                for name, ext in app.extensions.items():
                    if name not in ('database', 'redis', 'memcache'):
                        # can't share asyncio-based connections prior inicialization
                        sub_app[name] = ext
                        sub_app.extensions[name] = ext
            except (KeyError, AttributeError) as err:
                logging.warning(err)
        except ImportError as err:
            logging.warning(err)
            continue


class AppHandler(ABC):
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
        # App Name
        if not app_name:
            self._name = type(self).__name__
        else:
            self._name = app_name
        self.debug = DEBUG
        if not self.staticdir:
            self.staticdir = STATIC_DIR
        self.logger = get_logger(APP_NAME)
        # configuring asyncio loop
        if evt:
            self._loop = evt
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.app = self.CreateApp()
        # config
        self.app["config"] = context
        # register signals for startup cleanup and shutdown
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.pre_cleanup)
        self.app.on_cleanup.append(self.on_cleanup)
        self.app.on_shutdown.append(self.on_shutdown)
        self.app.on_response_prepare.append(self.on_prepare)
        self.app.cleanup_ctx.append(self.background_tasks)
        if self.enable_pgpool is True:
            try:
            # enable a pool-based database connection:
                pool = PostgresPool(
                    dsn=default_dsn,
                    name='Program',
                    startup=self.app_startup
                )
                pool.configure(self.app, register='database') # pylint: disable=E1123
            except (ProviderError, DriverError) as ex:
                raise web.HTTPServerError(
                    reason=f"Error creating Database connection: {ex}"
                )

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def CreateApp(self) -> web.Application:
        if DEBUG:
            cPrint(f"SETUP APPLICATION: {self._name!s}")
        self.cors = None
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
            router=Router()
        )
        app.router.add_route("GET", "/ping", ping, name="ping")
        app["name"] = self._name
        if 'extensions' not in app:
            app.extensions = {} # empty directory of extensions
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
        # CORS
        self.cors = aiohttp_cors.setup(
            app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_methods="*",
                    allow_headers="*",
                    max_age=3600,
                )
            },
        )
        return app

    @property
    def App(self) -> web.Application:
        return self.app

    @property
    def Name(self) -> str:
        return self._name

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

    async def background_tasks(self, app: web.Application): # pylint: disable=W0613
        """backgroud_tasks.

        perform asynchronous operations just after application start-up.
        Using the Cleanup Context logic.

        code before yield is an initialization stage (called on startup),
        code after yield is executed on cleanup
        """
        yield

    async def on_prepare(self, request, response):
        """
        on_prepare.
        description: Signal for customize the response while is prepared.
        """

    async def pre_cleanup(self, app):
        """
        pre_cleanup.
        description: Signal for customize the response when server is closing
        """

    async def on_cleanup(self, app):
        """
        on_cleanup.
        description: Signal for customize the response when server is closing
        """

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """

    async def app_startup(self, app: web.Application, connection: Callable):
        """app_startup
        description: Signal for making initialization after on_startup.
        """


class AppBase(AppHandler):
    _middleware: list = []


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
