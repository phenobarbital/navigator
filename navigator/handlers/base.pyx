# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
import asyncio
import inspect
from collections.abc import Callable
from aiohttp import web
from aiohttp.abc import AbstractView
import aiohttp_cors
from pathlib import Path
from navconfig import config, DEBUG, BASE_DIR
from navigator.functions import cPrint
from navigator.types import WebApp
from navigator.utils.functions import get_logger
# make a home and a ping class
from navigator.resources import ping
from navigator.exceptions import NavException


cdef class BaseHandler:
    """BaseHandler.

    Base for all application handlers, is an Abstract class for all Application constructors.
    """
    _middleware: list = []
    enable_static: bool = False
    staticdir: str = None

    def __init__(
        self,
        context: dict,
        app_name: str = None,
        evt: asyncio.AbstractEventLoop = None
    ) -> None:

        # App:
        self.app: WebApp = None
        # App Name
        if not app_name:
            self._name = type(self).__name__
        else:
            self._name = app_name
        self.debug = DEBUG
        self.logger = get_logger(self._name)
        if self.staticdir is None:
            self.staticdir = config.get('STATIC_DIR', fallback='static/')
        # configuring asyncio loop
        if evt:
            self._loop = evt
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        ### create the App inside Application Wrapper.
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

    def CreateApp(self) -> WebApp:
        if self.debug:
            cPrint(f"SETUP APPLICATION: {self._name!s}")
        self.cors = None
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
            loop=self._loop
        )
        app.router.add_route("GET", "/ping", ping, name="ping")
        app["name"] = self._name
        if 'extensions' not in app:
            app.extensions = {} # empty directory of extensions
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

    def configure(self) -> None:
        """
        configure.
            making configuration of routes and extensions.
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

    def add_routes(self, routes: list) -> None:
        """
        add_routes
        description: append a list of routes to routes dict
        """
        # TODO: avoid to add same route different times
        try:
            self.app.add_routes(routes)
        except Exception as ex:
            raise NavException(
                f"Error adding routes: {ex}"
            ) from ex

    def event_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def App(self) -> WebApp:
        return self.app

    @property
    def Name(self) -> str:
        return self._name


    async def background_tasks(self, app: WebApp): # pylint: disable=W0613
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


    async def app_startup(self, app: WebApp, connection: Callable):
        """app_startup
        description: Signal for making initialization after on_startup.
        """
