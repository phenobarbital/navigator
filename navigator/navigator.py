#!/usr/bin/env python3
import typing
import sys
from aiohttp import web
import aiohttp_cors
import argparse
import ssl
import asyncio
import uvloop
import logging
from navigator.conf import config, SECRET_KEY, APP_DIR, BASE_DIR, EMAIL_CONTACT, STATIC_DIR, Context, INSTALLED_APPS, LOCAL_DEVELOPMENT
from navigator.applications import AppHandler, app_startup
from aiohttp_swagger import setup_swagger
import sockjs
from typing import Callable, Optional, Any
import inspect
from aiohttp.abc import AbstractView
from aiohttp_session import setup as setup_session, get_session
from navigator.resources import WebSocket, channel_handler
# get the authentication library
from navigator.modules.auth import AuthHandler
from navigator.modules.session import navSession

from functools import wraps
#from apps.setup import app_startup
from aiohttp_utils import run as runner

# make asyncio use the event loop provided by uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
from concurrent.futures import ThreadPoolExecutor

class Application(object):
    app: Any = None
    debug = False
    parser = None
    use_ssl = False
    _routes: list = []
    _reload = False
    _logger = None
    path = ''
    host = '0.0.0.0'
    port = 5000
    _loop = None

    def __init__(self, app: AppHandler,  *args : typing.Any, **kwargs : typing.Any):
        self._loop = asyncio.get_event_loop()
        self._executor = ThreadPoolExecutor()
        if 'debug' in kwargs:
            self.debug = kwargs['debug']
        self.parser = argparse.ArgumentParser(description="Navigator App")
        self.parser.add_argument('--path')
        self.parser.add_argument('--host')
        self.parser.add_argument('--port')
        self.parser.add_argument('-d', '--debug', action='store_true')
        self.parser.add_argument('-r', '--reload', action='store_true')
        self.parse_arguments()
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
                self.host = '0.0.0.0'
        except (KeyError, ValueError, TypeError):
            self.host = '0.0.0.0'
        try:
            self.port = args.port
            if not self.port:
                self.port = 5000
        except (KeyError, ValueError, TypeError):
            self.port = 5000
        try:
            self.debug = args.debug
        except (KeyError, ValueError, TypeError):
            pass
        try:
            self._reload = args.reload
        except (KeyError, ValueError, TypeError):
            self._reload = False

    def get_app(self) -> web.Application:
        return self.app.App

    def get_logger(self, name="Navigator"):
        logging_format = f"[%(asctime)s] %(levelname)-5s %(name)-{len(name)}s "
        # logging_format += "%(module)-7s::l%(lineno)d: "
        # logging_format += "%(module)-7s: "
        logging_format += "%(message)s"
        logging.basicConfig(
            format=logging_format, level=logging.INFO, datefmt="%Y:%m:%d %H:%M:%S"
        )
        logging.getLogger('asyncio').setLevel(logging.INFO)
        logging.getLogger('websockets').setLevel(logging.INFO)
        logging.getLogger('aiohttp.web').setLevel(logging.INFO)
        return logging.getLogger(name)

    def setup_app(self) -> web.Application:
        app = self.get_app()
        # # TODO: iterate over modules folder
        # auth = AuthHandler()
        # auth.configure(app)
        # setup The Application and Sub-Applications Startup
        app_startup(INSTALLED_APPS, app, Context)
        # Configure Routes
        self.app.configure()
        self.app.set_cors()
        # auto-configure swagger
        long_description = """
        Asynchronous RESTful API for data source connections, REST consumer and Query API, used by Navigator, powered by MobileInsight
        """
        setup_swagger(app,
            api_base_url='/',
            title='API',
            api_version='2.0.0',
            description=long_description,
            contact=EMAIL_CONTACT,
            swagger_url="/api/doc")
        # TODO: configure documentation
        return app

    def add_websockets(self) -> None:
        """
        add_websockets.
        description: enable support for websockets in the main App
        """
        app = self.get_app()
        if self.debug:
            print('Enabling WebSockets')
        # websockets
        app.router.add_route('GET', '/ws', WebSocket)
        # websocket channels
        app.router.add_route('GET', '/ws/{channel}', channel_handler)

    def add_routes(self, routes : list) -> None:
        """
        add_route
        description: append a route to routes dict
        """
        # TODO: avoid to add same route different times
        #self._routes.append(route)
        self.get_app().add_routes(routes)

    def add_static(self, route: str, path: str):
        """
        add_static
        description: register new route to static path.
        """
        self.get_app().add_static(route, path)

    def threaded_func(self, func: Callable, threaded: bool =False):
        @wraps(func)
        async def _wrap(request):
            result = None
            try:
                if threaded:
                    def blocking_function():
                        return asyncio.new_event_loop().run_until_complete(func(request))
                    result = await self._loop.run_in_executor(self._executor, blocking_function)
                else:
                    result = (await func(request))
                return result
            except Exception as err:
                self._logger.exception(err)
        return _wrap

    def route(self, route: str, method: str = 'GET', threaded: bool =False):
        """
        route.
        description: decorator for register a new HTTP route.
        """
        def _decorator(func):
            self.app.App.router.add_route(method, route, self.threaded_func(func, threaded))
            return func
        return _decorator

    def add_get(self, route: str, threaded: bool =False) -> Callable:
        def _decorator(func):
            self.app.App.router.add_get(route, self.threaded_func(func, threaded))
            return func
        return _decorator

    def add_sock_endpoint(self, handler: Callable, name: str, route: str = '/sockjs/') -> None:
        app = self.get_app()
        sockjs.add_endpoint(app, handler, name=name, prefix=route)

    def run(self):
        # getting the app
        # getting the resource App
        app = self.setup_app()
        if self.debug is True:
            if LOCAL_DEVELOPMENT:
                import aiohttp_debugtoolbar
                from aiohttp_debugtoolbar import toolbar_middleware_factory
                aiohttp_debugtoolbar.setup(app, hosts=[self.host], enabled=True)
            if self._reload:
                runner(
                    app=app,
                    app_uri="navigator.runserver:app",
                    reload=True,
                    port=self.port,
                    host=self.host
                )
            else:
                web.run_app(app, host=self.host, port=self.port)
        else:
            if self.use_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                ssl_context.load_cert_chain(SSL_CERT, SSL_KEY)
                web.run_app(app, host=self.host, port=self.port, ssl_context=ssl_context)
            if self.path:
                web.run_app(app, path=self.path)
            else:
                web.run_app(app, host=self.host, port=self.port)
