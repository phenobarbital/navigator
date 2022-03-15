#!/usr/bin/env python3
import ssl
import aiohttp_cors
import signal
import sockjs
import traceback
import argparse
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import (
    List,
    Dict,
    Any,
    Callable,
    Optional
)
# make asyncio use the event loop provided by uvloop
import asyncio
import uvloop
from navigator.conf import (
    DEBUG,
    APP_NAME,
    APP_HOST,
    APP_PORT,
    EMAIL_CONTACT,
    INSTALLED_APPS,
    LOCAL_DEVELOPMENT,
    Context,
    SSL_CERT,
    SSL_KEY,
    TEMPLATE_DIR,
    CACHE_URL,
    default_dsn
)
from navigator.connections import PostgresPool, RedisPool
from navigator.applications import AppBase, AppHandler, app_startup
# Exception Handlers
from navigator.handlers import (
    nav_exception_handler,
    shutdown
)
from navigator.templating import TemplateParser
# websocket resources
from navigator.resources import WebSocket, channel_handler
from navconfig.logging import logging

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


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
    response = {
        "content_type": content_type,
        "charset": charset,
        "status": status
    }
    if headers:
        response["headers"] = headers
    if isinstance(content, str) or text is not None:
        response["text"] = content if content else text
    else:
        response["body"] = content if content else body
    return web.Response(**response)


class Application(object):
    def __init__(
        self,
        app: AppHandler = None,
        enable_swagger: bool = False,
        enable_debugtoolbar: bool = False,
        enable_jinja_parser: bool = True,
        use_ssl: bool = False,
        title: str = '',
        description: str = 'NAVIGATOR APP',
        contact: str = '',
        version: str = "0.0.1",
        swagger_options: Dict = {},

        *args,
        **kwargs
    ) -> None:
        self.version = version
        self.enable_debugtoolbar = enable_debugtoolbar
        self.enable_swagger = enable_swagger
        self.use_ssl = use_ssl
        self.description = description
        self.contact = contact
        if not contact:
            self.contact = EMAIL_CONTACT
        self.title = title
        if not title:
            self.title = APP_NAME
        self.swagger_options = swagger_options
        self.enable_jinja_parser = enable_jinja_parser
        # configuring asyncio loop
        # TODO: work in an exception handler for NAV
        self._loop = asyncio.get_event_loop()
        self._loop.set_exception_handler(nav_exception_handler)
        # May want to catch other signals too
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            self._loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(
                    shutdown(self._loop, s)
                )
            )
        self.parser = argparse.ArgumentParser(
            description="Navigator App"
        )
        self.parser.add_argument("--path")
        self.parser.add_argument("--host")
        self.parser.add_argument("--port")
        self.parser.add_argument(
            "-d", "--debug", action="store_true", help="Enable Debug"
        )
        self.parser.add_argument(
            "--traceback", action="store_true", help="Return Traceback on Error"
        )
        self.parse_arguments()
        if not app:
            # create an instance of AppHandler
            self.app = AppBase(Context)
        else:
            self.app = app(Context)
        # getting the application Logger
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
                self.host = APP_HOST
        except (KeyError, ValueError, TypeError):
            self.host = APP_HOST
        try:
            self.port = args.port
            if not self.port:
                self.port = APP_PORT
        except (KeyError, ValueError, TypeError):
            self.port = APP_PORT
        try:
            self.debug = args.debug
        except (KeyError, ValueError, TypeError):
            self.debug = DEBUG

    def get_app(self) -> web.Application:
        return self.app.App

    def __setitem__(self, k, v):
        self.app.App[k] = v

    def __getitem__(self, k):
        return self.app.App[k]

    def get_logger(self, name:str = APP_NAME):
        return logging.getLogger(name)

    def setup_app(self) -> web.Application:
        app = self.get_app()
        if self.enable_jinja_parser is True:
            try:
                parser = TemplateParser(
                    directory=TEMPLATE_DIR
                )
                app['template'] = parser
            except Exception:
                raise
        # create the pool-based connections (shared):
        name = app["name"]
        redis = RedisPool(
            dsn=CACHE_URL,
            name=f"NAV-{name!s}",
            loop=self._loop
        )
        redis.configure(app)
        app['redis'] = redis.connection()
        # Database Pool:
        db = PostgresPool(
            dsn=default_dsn,
            name=f"NAV-{name!s}",
            loop=self._loop
        )
        db.configure(app)
        app['database'] = db.connection()
        # setup The Application and Sub-Applications Startup
        app_startup(INSTALLED_APPS, app, Context)
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
                        ThreadPoolExecutor(max_workers=1), blocking_function
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
                route, self.threaded_func(func, threaded), allow_head=False
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

    @property
    def router(self):
        return self.app.App.router

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
        if self.debug:
            logging.debug('Running in DEBUG mode.')
        if self.enable_swagger is True:
            # previous to run, setup swagger:
            # auto-configure swagger
            from aiohttp_swagger import setup_swagger
            setup_swagger(
                app,
                api_base_url="/",
                title=self.title,
                api_version=self.version,
                description=self.description,
                swagger_url="/api/v1/doc",
                ui_version=3,
                **self.swagger_options
            )
        if self.debug is True:
            if LOCAL_DEVELOPMENT:
                if self.enable_debugtoolbar is True:
                    import aiohttp_debugtoolbar
                    from aiohttp_debugtoolbar import toolbar_middleware_factory
                    aiohttp_debugtoolbar.setup(
                        app,
                        hosts=[self.host, "127.0.0.1", "::1"],
                        enabled=True,
                        path_prefix="/_debug",
                    )
            try:
                web.run_app(app, host=self.host, port=self.port)
            except Exception as err:
                print(traceback.format_exc())
                print(err)
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
