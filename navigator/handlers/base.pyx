# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
import asyncio
import inspect
from collections.abc import Callable
from aiohttp import web
from aiohttp.abc import AbstractView
import aiohttp_cors
from aiohttp_cors import setup as cors_setup, ResourceOptions
from pathlib import Path
from navconfig import config, DEBUG, BASE_DIR
from ..functions import cPrint
from ..types import WebApp
from ..utils.functions import get_logger
# make a home and a ping class
from ..resources import ping, home
from ..exceptions import NavException


cdef class BaseAppHandler:
    """BaseAppHandler.

    Base for all application handlers,
    is an Abstract class for all Application constructors.
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
            self._loop = asyncio.get_event_loop()
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
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024
        )
        app.router.add_route("GET", "/ping", ping, name="ping")
        app.router.add_route("GET", "/", home, name="home")
        app["name"] = self._name
        if 'extensions' not in app:
            app.extensions = {} # empty directory of extensions
        # CORS
        self.cors = cors_setup(
            app,
            defaults={
                "*": ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_methods="*",
                    allow_headers="*",
                    max_age=1600,
                )
            },
        )
        return app

    def setup_cors(self) -> None:
        # CORS:
        for route in list(self.app.router.routes()):
            try:
                if not isinstance(route.resource, web.StaticResource):
                    if inspect.isclass(route.handler) and issubclass(
                        route.handler, AbstractView
                    ):
                        self.cors.add(route, webview=True)
                    else:
                        self.cors.add(route)
            except (TypeError, ValueError, RuntimeError) as exc:
                if 'already has OPTIONS handler' in str(exc):
                    continue
                self.logger.warning(
                    f"Error setting up CORS for route {route}: {exc}"
                )
                continue

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

    def add_view(self, route: str, view: Callable) -> None:
        self.app.router.add_view(route, view)
        try:
            self.cors.add(route, webview=True)
        except RuntimeError as ex:
            pass

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
