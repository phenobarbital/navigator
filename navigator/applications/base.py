# Copyright (C) 2018-present Jesus Lara
#
"""BaseApplication — pure-Python implementation.

Spec FEAT-001 / TASK-002 — converted from ``base.pyx``. The Cython version
relied on ``from ..handlers.base cimport BaseAppHandler``, which forced
``handlers/base.pyx`` to stay Cython as well. Since TASK-001 benchmarks
showed that Cython offers no performance benefit for ``BaseAppHandler``
(actually −31 %), both modules are converted together and the ``cimport``
is replaced by a regular Python import.
"""
from __future__ import annotations

import asyncio
import logging as _stdlib_logging
from typing import Any, Optional

from navconfig import DEBUG
from navconfig.logging import logging, loglevel

from ..conf import (
    APP_HOST,
    APP_NAME,
    APP_PORT,
    EMAIL_CONTACT,
    USE_SSL,
    Context,  # noqa: F401 — re-exported for backward compat
)
from ..handlers.base import BaseAppHandler
from ..types import WebApp


class BaseApplication:
    """Top-level Navigator application wrapper.

    Holds an :class:`~navigator.handlers.base.BaseAppHandler` instance
    (which in turn owns the underlying ``aiohttp.web.Application``) and
    exposes convenience accessors (``get_app``, ``active_extensions``,
    dict-like item access, etc.).

    Attributes:
        handler: The attached :class:`BaseAppHandler` (set by subclasses
            / :meth:`setup_app`).
        title: Logical application title — defaults to ``APP_NAME``.
        contact: Contact email — defaults to ``EMAIL_CONTACT``.
        host/port: Socket binding; may be overridden via kwargs.
        use_ssl: Mirrors the ``USE_SSL`` environment flag.
        debug: Mirrors the global ``DEBUG`` flag.
        logger: A navconfig-configured logger named after ``title``.
    """

    def __init__(
        self,
        handler: Optional[type] = None,
        title: str = "",
        contact: str = "",
        description: str = "NAVIGATOR APP",
        evt: asyncio.AbstractEventLoop | None = None,
        **kwargs: Any,
    ) -> None:
        # Application handler — populated by subclasses/``setup_app``.
        self.handler: BaseAppHandler | None = None
        self.description: str = description
        self.host = kwargs.pop("host", APP_HOST)
        self.port = kwargs.pop("port", APP_PORT)
        self.path = None
        self.title = title if title else APP_NAME
        self.contact = contact
        if not contact:
            self.contact = EMAIL_CONTACT
        self.use_ssl = USE_SSL
        self.debug = DEBUG
        self.logger: _stdlib_logging.Logger = logging.getLogger(self.title)
        self.logger.setLevel(loglevel)
        if self.debug is False:
            # Also disable logging for 'aiohttp.access'
            aio = logging.getLogger("aiohttp.access")
            aio.setLevel(logging.CRITICAL)
        # asyncio loop
        self._loop = evt

    def get_app(self) -> WebApp:
        return self.handler.app

    def setup_app(self) -> WebApp:
        pass

    def event_loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def __setitem__(self, k, v) -> None:
        self.handler.app[k] = v

    def __getitem__(self, k):
        return self.handler.app[k]

    def __repr__(self) -> str:
        return f"<App: {self.title}>"

    def active_extensions(self) -> list:
        return self.handler.app.extensions.keys()

    def setup(self) -> WebApp:
        """Return the NAV application object used by Gunicorn."""
        # getting the resource App
        app = self.setup_app()
        return app
