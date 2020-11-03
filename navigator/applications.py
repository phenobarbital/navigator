#!/usr/bin/env python3
import asyncio
import importlib
import inspect

# logging system
import logging
import os
import sys
import typing
from abc import ABC, abstractmethod
from logging.config import dictConfig

# from aiohttp_swagger import setup_swagger
from pathlib import Path
from typing import Any, Callable, Dict, List

import aiohttp_cors
import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web import middleware
from aiojobs.aiohttp import setup, spawn
from asyncdb import AsyncPool
from asyncdb.providers.redis import redis

from navigator.conf import (
    API_NAME,
    APP_DIR,
    BASE_DIR,
    DEBUG,
    INSTALLED_APPS,
    STATIC_DIR,
    logdir,
)
from navigator.middlewares import basic_middleware

# make a home and a ping class
from navigator.resources import home, ping

loglevel = logging.INFO

logger_config = dict(
    version=1,
    formatters={
        "console": {"format": "%(message)s"},
        "file": {
            "format": "%(asctime)s: [%(levelname)s]: %(pathname)s: %(lineno)d: \n%(message)s\n"
        },
        "default": {"format": "[%(levelname)s] %(asctime)s %(name)s: %(message)s"},
    },
    handlers={
        "console": {
            "formatter": "console",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "level": loglevel,
        },
        "StreamHandler": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": loglevel,
        },
    },
    root={
        "handlers": ["StreamHandler"],
        "level": loglevel,
    },
)
dictConfig(logger_config)

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
    app.router.add_route("GET", "/ping", ping)
    # index
    app.router.add_get("/", home)
    for app_name in app_list:
        obj = None
        try:
            name = app_name.split(".")[1]
            app_class = importlib.import_module(app_name, package="apps")
            obj = getattr(app_class, name)
            instance = obj(context, **kwargs)
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
    __version__: str = "0.0.1"
    app_description: str = ""
    cors = None
    _middleware: Any = None
    auto_home: bool = True
    enable_aiojobs: bool = False
    enable_static: bool = True
    staticdir: str = ""

    def __init__(self, context: dict, *args: List, **kwargs: dict):
        self._name = type(self).__name__
        self.logger = logging.getLogger(self._name)
        # configuring asyncio loop
        self._loop = asyncio.get_event_loop()
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
            self.app.router.add_route("GET", "/ping", ping)
            self.app.router.add_route("GET", "/", home)

    def CreateApp(self) -> web.Application:
        if DEBUG:
            print("SETUP NEW APPLICATION: {}".format(self._name))
        middlewares = {}
        self.cors = None
        if self._middleware:
            middlewares = {"middlewares": self._middleware}
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
            loop=self._loop,
            **middlewares
        )
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
        if self.enable_aiojobs:
            # Adding setup and support for aiojobs
            setup(self.app)
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
        for route in list(self.app.router.routes()):
            fn = route.handler
            signature = inspect.signature(fn)
            doc = fn.__doc__
            if doc is None:
                # TODO: making more efficiently
                fnName = fn.__name__
                if signature.return_annotation:
                    response = str(signature.return_annotation)
                else:
                    response = "unknown"
                if fnName not in [
                    "_handle",
                    "channel_handler",
                    "WebSocket",
                    "websocket",
                ]:
                    doc = """
                    summary: {fnName}
                    produces:
                    - text/plain
                    responses:
                        "200":
                            description: Successful operation
                            content:
                                {response}""".format(
                        fnName=fnName, response=response
                    )
                    try:
                        fn.__doc__ = doc
                    except (AttributeError, ValueError):
                        pass

    def setup_cors(self, cors):
        for route in list(self.app.router.routes()):
            try:
                # if DEBUG:
                #     self.logger.info(f'Adding CORS to {route.method} {route.handler}')
                # if not isinstance(route.resource, web.StaticResource):
                if inspect.isclass(route.handler) and issubclass(
                    route.handler, AbstractView
                ):
                    cors.add(route, webview=True)
                else:
                    cors.add(route)
            except ValueError as err:
                print("Error on Adding CORS: ", err)
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

    def __init__(self, *args: List, **kwargs: dict):
        self._name = type(self).__name__
        super(AppConfig, self).__init__(*args, **kwargs)
        self.path = APP_DIR.joinpath(self._name)
        # configure templating:
        if self.template:
            template_dir = os.path.join(self.path, self.template)
            # template_dir = self.path.resolve().joinpath(self.template)
            aiohttp_jinja2.setup(self.app, loader=jinja2.FileSystemLoader(template_dir))
        # set the setup_routes
        self.setup_routes()

    async def on_cleanup(self, app):
        await app["redis"].close()

    async def on_startup(self, app):
        kwargs = {"server_settings": {"client_min_messages": "notice"}}
        pool = AsyncPool(
            "pg",
            dsn=app["config"]["asyncpg_url"],
            loop=self._loop,
            timeout=360000,
            **kwargs
        )
        await pool.connect()
        await self.open_connection(pool, app)
        app["pool"] = pool
        # redis Pool
        rd = redis(dsn=app["config"]["cache_url"], loop=self._loop)
        await rd.connection()
        app["redis"] = rd

    async def open_connection(self, pool, app):
        try:
            conn = await pool.acquire()
            app['connection'] = conn
            if conn:
                if self.enable_notify:
                    connection = conn.engine()
                    #print(connection.get_server_version())
                    await connection.add_listener(self._name, self.listener)
                    await connection.execute('NOTIFY "{}", \'= Starting Navigator Notify System = \''.format(self._name))
        except Exception as err:
            raise Exception(err)

    async def on_shutdown(self, app):
        await self.close_connection(app["connection"])
        await app["pool"].wait_close(gracefully=False)

    def listener(conn, pid, channel, payload, *args):
        print("Notification from {}: {}, {}".format(channel, payload, args))

    async def close_connection(self, conn):
        try:
            if conn:
                if self.enable_notify:
                    await conn.engine().remove_listener(self._name, self.listener)
                    await asyncio.sleep(1)
                await conn.close()
        except Exception as err:
            print("Error closing Interface connection {}".format(err))
        # finally:
        #     print('= Closing {} connections'.format(self._name))

    def setup_routes(self):
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
            if inspect.isclass(route.handler) and issubclass(
                route.handler, AbstractView
            ):
                if not route.method:
                    r = self.app.router.add_view(
                        route.url, route.handler, name=route.name
                    )
                elif route.method == "*":
                    r = self.app.router.add_route(
                        "*", route.url, route.handler, name=route.name
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
                    self.cors.add(r)
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
                    else:
                        raise (
                            "Unsupported Method for Route {}, program: {}".format(
                                route.method, self._name
                            )
                        )
                        return False
                    self.cors.add(r)
