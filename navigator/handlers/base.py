# Copyright (C) 2018-present Jesus Lara
#
"""BaseAppHandler — pure-Python implementation.

Spec FEAT-001 / TASK-002 — converted from ``base.pyx``. The Cython version
was ~31 % *slower* than the equivalent pure-Python class in TASK-001
benchmarks (see ``benchmarks/results/cython_benchmarks.json``). The
conversion unlocks:

* native instance ``__dict__`` (no more ``cdef class`` attribute
  restrictions when subclassing from Python),
* standard ``.pyi`` typing support without a separate stub file,
* one less moving part in the build.

The public API (class name, attributes, method signatures, registered
aiohttp signals) is preserved exactly; callers that inherit
``BaseAppHandler`` keep working without any source change.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

import aiohttp_cors
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp_cors import ResourceOptions, setup as cors_setup

from ..exceptions import NavException
from ..functions import cPrint
from ..resources import home, ping
from ..types import WebApp
from ..utils.functions import get_logger


class BaseAppHandler:
    """BaseAppHandler.

    Base for all application handlers — an abstract scaffold that builds
    an :class:`aiohttp.web.Application` with CORS, default routes, and
    lifecycle signals wired up. Subclasses (e.g.
    :class:`navigator.handlers.types.AppHandler`) layer database pools,
    middlewares, and authentication on top of this foundation.
    """

    _middleware: list = []
    enable_static: bool = False
    staticdir: str | None = None
    show_static_index: bool = False
    config: Callable | None = None

    def __init__(
        self,
        context: dict,
        app_name: str | None = None,
        evt: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Initialise the handler and its wrapped aiohttp application.

        Args:
            context: Arbitrary per-application context dict; stored on
                ``app['config']``.
            app_name: Optional logical name. Defaults to the class name.
            evt: Optional event loop. If not supplied the current loop is
                used (legacy behavior preserved).
        """
        from navconfig import DEBUG, config

        self.app: WebApp | None = None
        self.config: Any = config
        if not app_name:
            self._name = type(self).__name__
        else:
            self._name = app_name
        self.debug = DEBUG
        self.logger = get_logger(self._name)
        if self.staticdir is None:
            self.staticdir = config.get("STATIC_DIR", fallback="static/")
        # configuring asyncio loop
        if evt:
            self._loop = evt
        else:
            self._loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self._loop)
        # create the App inside the Application wrapper.
        self.app = self.CreateApp()
        # config
        self.app["config"] = context
        # register signals for startup, cleanup, and shutdown
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.pre_cleanup)
        self.app.on_cleanup.append(self.on_cleanup)
        self.app.on_shutdown.append(self.on_shutdown)
        self.app.on_response_prepare.append(self.on_prepare)
        self.app.cleanup_ctx.append(self.background_tasks)

    def CreateApp(self) -> WebApp:
        """Build the underlying :class:`aiohttp.web.Application`."""
        if self.debug:
            cPrint(f"SETUP APPLICATION: {self._name!s}")
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
        )
        app.router.add_route("GET", "/ping", ping, name="ping")
        app.router.add_route("GET", "/", home, name="home")
        app["name"] = self._name
        # configure Config
        self._set_config(app, self.config)
        if "extensions" not in app:
            app.extensions = {}  # empty directory of extensions
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

    def _set_config(
        self,
        app: WebApp,
        conf: Callable,
        key_name: str = "config",
    ) -> None:
        """Set application configuration.

        Args:
            app: Application instance.
            conf: Instance of Navconfig (Kardex).
            key_name: Key used to store the config on the aiohttp app.
        """
        from navconfig import Kardex

        if not isinstance(conf, Kardex):
            raise NavException("Configuration must be an instance of Navconfig")
        if hasattr(app, key_name):
            # already configured
            return
        config_key = web.AppKey(key_name, Kardex)
        app[config_key] = conf
        # also add as an attribute
        setattr(app, key_name, self.config)

    def setup_cors(self) -> None:
        """Register every non-static route with the CORS resource table."""
        for route in list(self.app.router.routes()):
            try:
                if not isinstance(route.resource, web.StaticResource):
                    if inspect.isclass(route.handler) and issubclass(
                        route.handler, AbstractView
                    ):
                        self.cors.add(route)
                    else:
                        self.cors.add(route)
            except (TypeError, ValueError, RuntimeError) as exc:
                if "already has OPTIONS handler" in str(exc):
                    continue
                if "already has a " in str(exc):
                    continue
                self.logger.warning(
                    f"Error setting up CORS for route {route}: {exc}"
                )
                continue

    def configure(self) -> None:
        """Perform deferred configuration of routes and extensions."""
        if self.enable_static is True:
            # adding static directory.
            self.app.router.add_static(
                "/static/",
                path=self.staticdir,
                name="static",
                append_version=True,
                show_index=self.show_static_index,
                follow_symlinks=False,
            )

    def add_routes(self, routes: list) -> None:
        """Append a list of routes to the underlying aiohttp app."""
        # TODO: avoid adding the same route multiple times
        try:
            self.app.add_routes(routes)
        except Exception as ex:
            raise NavException(f"Error adding routes: {ex}") from ex

    def add_view(self, route: str, view: Callable) -> None:
        """Register a class-based view and wire it into CORS."""
        self.app.router.add_view(route, view)
        try:
            self.cors.add(route)
        except RuntimeError:
            # Already registered — safe to ignore.
            pass

    def event_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def App(self) -> WebApp:
        return self.app

    @property
    def Name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Lifecycle signals (all no-ops by default; subclasses override)
    # ------------------------------------------------------------------

    async def background_tasks(self, app: WebApp):  # pylint: disable=W0613
        """Run asynchronous operations around application startup.

        Using aiohttp's cleanup-context protocol: code before ``yield`` is
        initialization (called on startup); code after ``yield`` is
        executed on cleanup.
        """
        yield

    async def on_prepare(self, request, response):
        """Signal to customize the response as it is prepared."""

    async def pre_cleanup(self, app):
        """Signal fired right before the on_cleanup phase begins."""

    async def on_cleanup(self, app):
        """Signal fired during server cleanup."""

    async def on_startup(self, app):
        """Signal fired after the server has started."""

    async def on_shutdown(self, app):
        """Signal fired while the server is shutting down."""

    async def app_startup(self, app: WebApp, connection: Callable):
        """Signal for making initialization after on_startup."""
