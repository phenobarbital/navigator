#!/usr/bin/env python3
import asyncio
from abc import ABC, abstractmethod
import importlib
import inspect
import asyncio
import uvloop
from pathlib import Path
from typing import Any, Callable, Dict, List
import aiohttp_cors
from navigator.templating import TemplateParser

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractView

from navigator.conf import (
    APP_NAME,
    APP_DIR,
    DEBUG,
    STATIC_DIR,
    SESSION_TIMEOUT,
    default_dsn
)
from navigator.connections import PostgresPool
# make a home and a ping class
from navigator.resources import home, ping
from navigator.functions import cPrint
# get the authentication library
from navigator.auth import AuthHandler
from navconfig.logging import logging


asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

#######################
##
## PATH CONFIGURATION
##
#######################


class path(object):
    """
    path.
    description: django-like URL router configuration
    """

    method = ""
    url = ""
    handler = None
    name = ""

    def __init__(self, method, url, handler, name=""):
        self.method = method
        self.url = url
        self.handler = handler
        self.name = name


#######################
##
## APPS CONFIGURATION
##
#######################


def app_startup(app_list: list, app: web.Application, context: dict, **kwargs: dict):
    """ Initialize all Apps in the existing Installation."""
    for app_name in app_list:
        obj = None
        try:
            name = app_name.split(".")[1]
            app_class = importlib.import_module(app_name, package="apps")
            obj = getattr(app_class, name)
            instance = obj(context, **kwargs)
            domain = getattr(instance, "domain", None)
            sub_app = instance.App
            if domain:
                app.add_domain(domain, sub_app)
            else:
                app.add_subapp("/{}/".format(name), sub_app)
            # TODO: build automatic documentation
            # add other elements:
            try:
                sub_app['template'] = app["template"]
                # redis connection
                sub_app['redis'] = app['redis']
                if 'database' in app:
                    sub_app['database'] = app['database']
            except Exception as err:
                logging.warning(err)
        except ImportError as err:
            print(err)
            continue


class AppHandler(ABC):
    """
    AppHandler.

    Main Class for registration from Main aiohttp App Creation.
    can register Callbacks, Signals, Route Initialization, etc
     * TODO: adding support for middlewares
     * TODO: get APP names
    """
    _middleware: List = []
    auto_home: bool = True
    enable_notify: bool = False
    enable_static: bool = True
    enable_swagger: bool = True
    auto_doc: bool = False
    enable_auth: bool = True
    staticdir: str = None

    def __init__(
        self,
        context: dict,
        app_name: str = None,
        *args,
        **kwargs
    ) -> None:
        # App Name
        if not app_name:
            self._name = type(self).__name__
        else:
            self._name = app_name
        self.debug = DEBUG
        if not self.staticdir:
            self.staticdir = STATIC_DIR
        self.logger = logging.getLogger(APP_NAME)
        # configuring asyncio loop
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
        # TODO: making automatic discovery of routes
        if self.auto_home:
            self.app.router.add_route("GET", "/", home)

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def CreateApp(self) -> web.Application:
        if DEBUG:
            cPrint(f"SETUP APPLICATION: {self._name!s}", level="SUCCESS")
        middlewares = {}
        self.cors = None
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024
        )
        app.router.add_route("GET", "/ping", ping, name="ping")
        app.router.add_get("/", home, name="home")
        app["name"] = self._name
        # Setup Authentication:
        if self.enable_auth is True:
            self._auth = AuthHandler(
                session_timeout=SESSION_TIMEOUT
            )
            # configuring authentication endpoints
            self._auth.configure(
                app=app,
                handler=self
            )
            app["auth"] = self._auth
            ## add the authorization endpoint endpoint:
            app.router.add_get(
                '/{program}/authorize', self.app_authorization
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
            # adding statics
            self.app.router.add_static(
                "/static/",
                path=self.staticdir,
                name="static",
                append_version=True
            )

    def setup_docs(self) -> None:
        """
        set_cors.
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
                        response = aiohttp.web_response.Response
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
            except (Exception, ValueError) as err:
                # logging.warning(f"Warning on Adding CORS: {err!r}")
                pass
            
    async def app_authorization(self, request: web.Request) -> web.Response:
        app = request.app
        try:
            program = request.match_info['program']
        except Exception as err:
            print(err)
            program = None
        authorization = {
            "status": "Tenant Authorized",
            "program": program
        }
        return web.json_response(authorization, status=200)

    async def on_prepare(self, request, response):
        """
        on_prepare.
        description: Signal for customize the response while is prepared.
        """
        pass

    async def pre_cleanup(self, app):
        """
        pre_cleanup.
        description: Signal for customize the response when server is closing
        """
        pass

    async def on_cleanup(self, app):
        """
        on_cleanup.
        description: Signal for customize the response when server is closing
        """
        pass

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """
        pass

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """
        pass


class AppBase(AppHandler):
    _middleware = None


class AppConfig(AppHandler):
    """
    AppConfig.

    Class for Configuration of aiohttp SubApps
    """

    template: str = "templates"
    path: Path = None
    _middleware = None
    domain: str = ""
    version: str = '0.0.1'
    description: str = ''
    enable_pgpool: bool = False
    _listener: Callable = None

    def __init__(
        self,
        *args,
        **kwargs
    ):
        self._name = type(self).__name__
        super(AppConfig, self).__init__(*args, **kwargs)
        self.path = APP_DIR.joinpath(self._name)
        # configure templating:
        # TODO: Using the Template Handler exactly like others.
        if self.template:
            try:
                template_dir = self.path.resolve().joinpath(self.template)
                if template_dir.exists():
                    self.app['template'] = TemplateParser(
                        directory=template_dir
                    )
            except Exception as err:
                logging.warning(
                    f'Error Loading Template Parser for SubApp {self._name}: {err}'
                )
        # set the setup_routes
        self.setup_routes()
        # setup swagger
        if self.enable_swagger is True:
            from aiohttp_swagger import setup_swagger
            setup_swagger(
                self.app,
                api_base_url=f"/{self._name}",
                title=f"{self._name} API",
                api_version=self.version,
                description=self.description,
                swagger_url=f"/api/v1/doc",
                ui_version=3,
            )
        self.app.router.add_get(
            '/authorize', self.app_authorization
        )

    def listener(conn, pid, channel, payload, *args):
        print("Notification from {}: {}, {}".format(channel, payload, args))
        
    async def create_connection(self, app, dsn: str = None):
        if not dsn:
            dsn = default_dsn
        pool = PostgresPool(
            dsn=dsn,
            name=f"NAV-{self._name!s}",
            loop=self._loop
        )
        try:
            await pool.startup(app=app)
            app["database"] = pool.connection()
        except Exception as err:
            print(err)
            raise Exception(err)
        if self.enable_notify is True:
            await self.open_connection(app, self._listener)
        return pool.connection()

    async def close_connection(self, app):
        try:
            if self.enable_notify is True:
                conn = app["connection"]
                if conn:
                    await conn.engine().remove_listener(self._name, self.listener)
                    await asyncio.sleep(1)
                await conn.close()
        except Exception as err:
            logging.error("Error closing Interface connection {}".format(err))

    async def open_connection(self, app: web.Application, listener: Callable = None):
        if not listener:
            listener = self.listener
        try:
            conn = await app["database"].acquire()
            app["connection"] = conn
            if conn:
                connection = conn.engine()
                await connection.add_listener(self._name, listener)
                await connection.execute(
                    "NOTIFY \"{}\", '= Starting Navigator Notify System = '".format(
                        self._name
                    )
                )
        except Exception as err:
            raise Exception(err)

    async def on_startup(self, app):
        # enabled pgpool
        if self.enable_pgpool is True:
            try:
                await self.create_connection(app, default_dsn)
            except Exception:
                pass

    async def on_shutdown(self, app):
        if self.enable_pgpool is True:
            try:
                await self.close_connection(app)
            except Exception:
                pass

    def setup_routes(self):
        """Setup Routes (URLS) pointing to paths on AppConfig."""
        # set the urls
        # TODO: automatic module loader
        try:
            cls = importlib.import_module(
                "{}.{}".format("apps.{}".format(self._name), "urls"), package="apps"
            )
            routes = getattr(cls, "urls")
        except ImportError as err:
            print(err)
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
                        raise (
                            "Unsupported Method for Route {}, program: {}".format(
                                route.method, self._name
                            )
                        )
                        return False
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
                        raise (
                            "Unsupported Method for Route {}, program: {}".format(
                                route.method, self._name
                            )
                        )
                        return False
                    self.cors.add(r)

    async def app_authorization(self, request: web.Request) -> web.Response:
        app = request.app
        try:
            program = request.match_info['program']
        except Exception as err:
            program = self.__class__.__name__
        authorization = {
            "status": "Tenant Authorized",
            "program": program
        }
        return web.json_response(authorization, status=200)
