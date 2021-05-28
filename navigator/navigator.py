#!/usr/bin/env python3
import argparse
import ssl
import sys
import typing
import aiohttp_cors
from aiohttp import web
import inspect
import logging
import signal
import sockjs
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any, Callable, Optional

# make asyncio use the event loop provided by uvloop
import asyncio
import uvloop
from aiohttp import web
from aiohttp.abc import AbstractView

# Aiohttp Session
from aiohttp_session import get_session
from aiohttp_session import setup as setup_session
from aiohttp_session.redis_storage import RedisStorage
# from apps.setup import app_startup
from aiohttp_utils import run as runner

from navigator.conf import (
    DEBUG,
    APP_DIR,
    BASE_DIR,
    EMAIL_CONTACT,
    INSTALLED_APPS,
    LOCAL_DEVELOPMENT,
    NAV_AUTH_BACKEND,
    AUTHORIZATION_BACKENDS,
    CREDENTIALS_REQUIRED,
    SECRET_KEY,
    STATIC_DIR,
    Context,
    config,
    SSL_CERT,
    SSL_KEY
)

from navigator.applications import AppBase, AppHandler, app_startup

# Exception Handlers
from navigator.handlers import nav_exception_handler, shutdown

# websocket resources
from navigator.resources import WebSocket, channel_handler

# get the authentication library
from navigator.auth import AuthHandler

__version__ = "1.2.0"
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def get_version():
    return __version__


def Response(
    content: Any = None,
    text: str = "",
    body: Any = None,
    status: int = 200,
    headers: dict = None,
    content_type: str = "text/plain",
    charset: str = "utf-8",
) -> web.Response:
    """
    Response.
    Web Response Definition for Navigator
    """
    response = {"content_type": content_type, "charset": charset, "status": status}
    if headers:
        response["headers"] = headers
    if isinstance(content, str) or text is not None:
        response["text"] = content if content else text
    else:
        response["body"] = content if content else body
    return web.Response(**response)


class Application(object):
    app: Any = None
    _auth = None
    debug = False
    parser = None
    use_ssl = False
    _routes: list = []
    _reload = False
    _logger = None
    path = ""
    host = "0.0.0.0"
    port = 5000
    _loop = None
    version = "0.0.1"
    enable_swagger: bool = True
    disable_debugtoolbar: bool = True

    def __init__(
        self, app: AppHandler = None,
        *args: typing.Any,
        **kwargs: typing.Any
    ):
        # configuring asyncio loop
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            logging.error(
                "Couldn't get event loop for current thread. Creating a new event loop to be used!"
            )
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        # self._loop.set_exception_handler(nav_exception_handler)
        # May want to catch other signals too
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            self._loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(self._loop, s))
            )
        self._executor = ThreadPoolExecutor()
        if "debug" in kwargs:
            self.debug = kwargs["debug"]
        else:
            self.debug = DEBUG
        self.parser = argparse.ArgumentParser(description="Navigator App")
        self.parser.add_argument("--path")
        self.parser.add_argument("--host")
        self.parser.add_argument("--port")
        self.parser.add_argument("-r", "--reload", action="store_true")
        self.parser.add_argument(
            "-d", "--debug", action="store_true", help="Enable Debug"
        )
        self.parser.add_argument(
            "--traceback", action="store_true", help="Return the Traceback on Error"
        )
        self.parse_arguments()
        if not app:
            # create an instance of AppHandler
            self.app = AppBase(Context)
        else:
            self.app = app(Context)
        self._logger = self.get_logger(self.app.Name)

    def parse_arguments(self):
        args = self.parser.parse_args()
        try:
            self.path = args.path
        except (KeyError, ValueError, TypeError):
            self.path = None
        try:
            self.host = args.host
            if not self.host:
                self.host = "0.0.0.0"
        except (KeyError, ValueError, TypeError):
            self.host = "0.0.0.0"
        try:
            self.port = args.port
            if not self.port:
                self.port = 5000
        except (KeyError, ValueError, TypeError):
            self.port = 5000
        try:
            if args.debug:
                self.debug = args.debug
        except (KeyError, ValueError, TypeError):
            pass
        try:
            self._reload = args.reload
        except (KeyError, ValueError, TypeError):
            self._reload = False

    def get_app(self) -> web.Application:
        return self.app.App

    def __setitem__(self, k, v):
        self.app.App[k] = v

    def __getitem__(self, k):
        return self.app.App[k]

    def get_logger(self, name="Navigator"):
        logging_format = f"[%(asctime)s] %(levelname)-5s %(name)-{len(name)}s "
        # logging_format += "%(module)-7s::l%(lineno)d: "
        # logging_format += "%(module)-7s: "
        logging_format += "%(message)s"
        logging.basicConfig(
            format=logging_format, level=logging.INFO, datefmt="%Y:%m:%d %H:%M:%S"
        )
        return logging.getLogger(name)

    def setup_app(self) -> web.Application:
        app = self.get_app()
        self._auth = AuthHandler(
            backend=NAV_AUTH_BACKEND,
            credentials_required=CREDENTIALS_REQUIRED,
            authorization_backends=AUTHORIZATION_BACKENDS
        )
        # configuring authentication endpoints
        self._auth.configure(app)
        # setup The Application and Sub-Applications Startup
        app_startup(INSTALLED_APPS, app, Context)
        app["auth"] = self._auth

        # Configure Routes
        self.app.configure()
        cors = aiohttp_cors.setup(
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
        self.app.setup_cors(cors)
        self.app.setup_docs()
        return app

    def add_websockets(self) -> None:
        """
        add_websockets.
        description: enable support for websockets in the main App
        """
        app = self.get_app()
        if self.debug:
            logging.debug("Enabling WebSockets")
        # websockets
        app.router.add_route("GET", "/ws", WebSocket)
        # websocket channels
        app.router.add_route("GET", "/ws/{channel}", channel_handler)

    def add_routes(self, routes: list) -> None:
        """
        add_route
        description: append a route to routes dict
        """
        # TODO: avoid to add same route different times
        # self._routes.append(route)
        self.get_app().add_routes(routes)

    def add_static(self, route: str, path: str):
        """
        add_static
        description: register new route to static path.
        """
        self.get_app().add_static(route, path)

    def add_view(self, route: str, handler: Any):
        self.get_app().router.add_view(route, handler)

    def threaded_func(self, func: Callable, threaded: bool = False):
        @wraps(func)
        async def _wrap(request):
            result = None
            try:
                if threaded:

                    def blocking_function():
                        return asyncio.new_event_loop().run_until_complete(
                            func(request)
                        )

                    result = await self._loop.run_in_executor(
                        self._executor, blocking_function
                    )
                else:
                    result = await func(request)
                return result
            except Exception as err:
                self._logger.exception(err)

        return _wrap

    def route(self, route: str, method: str = "GET", threaded: bool = False):
        """
        route.
        description: decorator for register a new HTTP route.
        """

        def _decorator(func):
            self.app.App.router.add_route(
                method, route, self.threaded_func(func, threaded)
            )
            return func

        return _decorator

    def add_get(self, route: str, threaded: bool = False) -> Callable:
        def _decorator(func):
            self.app.App.router.add_get(
                route,
                self.threaded_func(func, threaded),
                allow_head=False
            )
            return func

        return _decorator

    def Response(self, content: Any) -> web.Response:
        return web.Response(text=content)

    def get(self, route: str):
        def _decorator(func):
            self.app.App.router.add_get(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self._logger.exception(err)

            return _wrap

        return _decorator

    def post(self, route: str):
        def _decorator(func):
            self.app.App.router.add_post(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self._logger.exception(err)

            return _wrap

        return _decorator

    def add_sock_endpoint(
        self, handler: Callable, name: str, route: str = "/sockjs/"
    ) -> None:
        app = self.get_app()
        sockjs.add_endpoint(app, handler, name=name, prefix=route)

    def run(self):
        # getting the resource App
        app = self.setup_app()
        # previous to run, setup swagger:
        # auto-configure swagger
        long_description = """
        Asynchronous RESTful API for data source connections, REST consumer \
        and Query API, used by Navigator, powered by MobileInsight
        """
        if self.enable_swagger is True:
            from aiohttp_swagger import setup_swagger
            setup_swagger(
                app,
                api_base_url='/',
                title='Navigator API',
                api_version=self.version,
                description=long_description,
                swagger_url="/api/v1/doc",
                ui_version=3
            )
        if self.debug is True:
            if LOCAL_DEVELOPMENT:
                if self.disable_debugtoolbar is False:
                    import aiohttp_debugtoolbar
                    from aiohttp_debugtoolbar import toolbar_middleware_factory
                    aiohttp_debugtoolbar.setup(
                        app,
                        hosts=[self.host,'127.0.0.1', '::1'],
                        enabled=True,
                        path_prefix='/_debug'
                    )
            if self._reload:
                runner(
                    app=app,
                    app_uri="navigator.runserver:app",
                    reload=True,
                    port=self.port,
                    host=self.host,
                )
            else:
                web.run_app(app, host=self.host, port=self.port)
        else:
            if self.use_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                ssl_context.load_cert_chain(SSL_CERT, SSL_KEY)
                web.run_app(
                    app, host=self.host, port=self.port, ssl_context=ssl_context
                )
            if self.path:
                web.run_app(app, path=self.path)
            else:
                web.run_app(app, host=self.host, port=self.port)
