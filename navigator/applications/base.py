import asyncio
from collections.abc import Callable
from abc import ABC
from aiohttp import web
import aiohttp_cors
from navconfig import DEBUG
from navigator.functions import cPrint
from navigator.types import WebApp
from navigator.utils.functions import get_logger
# make a home and a ping class
from navigator.resources import ping
# get the default Router system.
from navigator.routes import Router
from .conf import (
    STATIC_DIR
)


class BaseHandler(ABC):
    """
    BaseHandler.

    Abstract class for all Application constructors.
    """
    _middleware: list = []
    auto_doc: bool = False
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
        if not self.staticdir:
            self.staticdir = STATIC_DIR
        self.logger = get_logger(self._name)
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


    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def App(self) -> WebApp:
        return self.app

    @property
    def Name(self) -> str:
        return self._name

    def CreateApp(self) -> WebApp:
        if self.debug:
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
