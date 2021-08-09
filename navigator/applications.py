#!/usr/bin/env python3
import os
import sys
import typing
from abc import ABC, abstractmethod
import importlib
import inspect

# logging system
import logging
from logging.config import dictConfig
from pathlib import Path
from typing import Any, Callable, Dict, List

import aiohttp_cors
import aiohttp_jinja2
import jinja2

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web import middleware
from asyncdb import AsyncPool
from asyncdb.providers.redis import redis

from navigator.conf import (
    API_NAME,
    APP_DIR,
    BASE_DIR,
    DEBUG,
    INSTALLED_APPS,
    STATIC_DIR,
)
from navigator.connections import PostgresPool
from navconfig.logging import logdir, logging_config
from navigator.middlewares import basic_middleware

# make a home and a ping class
from navigator.resources import home  # ping
from navigator.functions import cPrint
import asyncio
import uvloop

# make asyncio use the event loop provided by uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

loglevel = logging.INFO
dictConfig(logging_config)

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
    # Configure the main App
    # app.router.add_route("GET", "/ping", ping)
    # index
    app.router.add_get("/", home)
    for app_name in app_list:
        obj = None
        try:
            name = app_name.split(".")[1]
            app_class = importlib.import_module(app_name, package="apps")
            obj = getattr(app_class, name)
            instance = obj(context, **kwargs)
            domain = getattr(instance, "domain", None)
            if domain:
                app.add_domain(domain, instance.App)
            else:
                app.add_subapp("/{}/".format(name), instance.App)
            # TODO: build automatic documentation
        except ImportError as err:
            print(err)
            continue


class AppHandler(ABC):
    """
    AppHandler.

    Main Class for registration of Callbacks, Signals, Route Initialization, etc
     * TODO: adding support for middlewares
     * TODO: get APP names
    """

    _name = None
    logger = None
    _loop = None
    debug = False
    app: web.Application = None
    app_name: str = ""
    __version__: str = "0.0.1"
    app_description: str = ""
    cors = None
    _middleware: Any = None
    auto_home: bool = True
    enable_notify: bool = False
    enable_static: bool = True
    enable_swagger: bool = True
    auto_doc: bool = False
    staticdir: str = ""

    def __init__(self, context: dict, *args: List, **kwargs: dict):
        self._name = type(self).__name__
        self.logger = logging.getLogger(self._name)
        # configuring asyncio loop
        self._loop = self.get_loop()
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
            # self.app.router.add_route("GET", "/ping", ping)
            self.app.router.add_route("GET", "/", home)

    def CreateApp(self) -> web.Application:
        if DEBUG:
            if not self.app_name:
                name = self._name
            else:
                name = self.app_name
            cPrint(f"SETUP APPLICATION: {name!s}", level="SUCCESS")
        middlewares = {}
        self.cors = None
        if self._middleware:
            middlewares = {"middlewares": self._middleware}
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
            loop=self._loop,
            **middlewares,
        )
        # print(app)
        app["name"] = self._name
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

    def get_loop(self, new: bool = False):
        if new is True:
            loop = uvloop.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop
        else:
            return asyncio.get_event_loop()

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
        if self.enable_static:
            # adding statics
            # TODO: can personalize the path
            static = self.staticdir if self.staticdir else STATIC_DIR
            self.app.router.add_static(
                "/static/", path=static, name="static", append_version=True
            )
            # self.app.add_routes(
            #     [web.static('/static', static, append_version=True)]
            # )

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
            except ValueError as err:
                # logging.warning(f"Warning on Adding CORS: {err!r}")
                pass

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
    enable_notify: bool = False
    domain: str = ""

    def __init__(self, *args: List, **kwargs: dict):
        self._name = type(self).__name__
        super(AppConfig, self).__init__(*args, **kwargs)
        self.path = APP_DIR.joinpath(self._name)
        # configure templating:
        # TODO: using Notify Logic about aiohttp jinja
        if self.template:
            template_dir = os.path.join(self.path, self.template)
            # template_dir = self.path.resolve().joinpath(self.template)
            aiohttp_jinja2.setup(self.app, loader=jinja2.FileSystemLoader(template_dir))
        # set the setup_routes
        self.setup_routes()
        # setup cors:
        # self.setup_cors(self.cors)
        if self.enable_swagger is True:
            from aiohttp_swagger import setup_swagger

            setup_swagger(
                self.app,
                api_base_url=f"/{self._name}",
                title=f"{self._name} API",
                api_version=self.__version__,
                description=self.app_description,
                swagger_url=f"/api/v1/doc",
                ui_version=3,
            )

    async def on_cleanup(self, app):
        try:
            await app["redis"].close()
        except Exception:
            logging.error("Error closing Redis connection")

    async def on_startup(self, app):
        # redis Pool
        rd = redis(dsn=app["config"]["cache_url"], loop=self._loop)
        await rd.connection()
        app["redis"] = rd
        # initialize models:

    async def create_connection(self, app, dsn: str = ""):
        if not dsn:
            dsn = app["config"]["asyncpg_url"]
        pool = PostgresPool(dsn=dsn, name=f"NAV-{self._name!s}", loop=self._loop)
        try:
            await pool.startup(app=app)
            app["database"] = pool.connection()
        except Exception as err:
            print(err)
            raise Exception(err)
        if self.enable_notify is True:
            await self.open_connection(app)

    async def close_connection(self, conn):
        try:
            if self.enable_notify is True:
                if conn:
                    await conn.engine().remove_listener(self._name, self.listener)
                    await asyncio.sleep(1)
                await conn.close()
        except Exception as err:
            logging.error("Error closing Interface connection {}".format(err))

    async def open_connection(self, app, listener: Callable = None):
        if not listener:
            listener = self.listener
        try:
            conn = await app["database"].acquire()
            app["connection"] = conn
            if conn:
                if self.enable_notify:
                    connection = conn.engine()
                    await connection.add_listener(self._name, listener)
                    await connection.execute(
                        "NOTIFY \"{}\", '= Starting Navigator Notify System = '".format(
                            self._name
                        )
                    )
        except Exception as err:
            raise Exception(err)

    async def on_shutdown(self, app):
        try:
            await app["database"].wait_close(timeout=5)
        except Exception:
            pass

    def listener(conn, pid, channel, payload, *args):
        print("Notification from {}: {}, {}".format(channel, payload, args))

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
