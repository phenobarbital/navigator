# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
import asyncio
from typing import Optional
from navconfig import config, DEBUG
from navconfig.logging import logging, loglevel
from ..types import WebApp
from ..conf import (
    APP_HOST,
    APP_PORT,
    APP_NAME,
    EMAIL_CONTACT,
    USE_SSL,
    Context
) # pylint: disable=C0415
from ..handlers.base cimport BaseAppHandler


cdef class BaseApplication:

    def __init__(
        self,
        handler: Optional[type] = None,
        title: str = '',
        contact: str = '',
        description: str = 'NAVIGATOR APP',
        evt: asyncio.AbstractEventLoop = None,
        **kwargs,
    ) -> None:
        ### Application handler:
        self.handler = None
        self.description: str = description
        self.host = kwargs.pop('host', APP_HOST)
        self.port = kwargs.pop('port', APP_PORT)
        self.path = None
        self.title = title if title else APP_NAME
        self.contact = contact
        if not contact:
            self.contact = EMAIL_CONTACT
        self.use_ssl = USE_SSL
        self.debug = DEBUG
        self.logger = logging.getLogger(self.title)
        self.logger.setLevel(loglevel)
        if self.debug is False:
            # also, disable logging for 'aiohttp.access'
            aio = logging.getLogger('aiohttp.access')
            aio.setLevel(logging.CRITICAL)
        ### asyncio loop
        self._loop = evt

    def get_app(self) -> WebApp:
        return self.handler.app

    def setup_app(self) -> WebApp:
        pass

    def event_loop(self):
        return self._loop

    def __setitem__(self, k, v):
        self.handler.app[k] = v

    def __getitem__(self, k):
        return self.handler.app[k]

    def __repr__(self):
        return f'<App: {self.title}>'

    def active_extensions(self) -> list:
        return self.handler.app.extensions.keys()

    def setup(self) -> WebApp:
        """setup.
        Get NAV application, used by Gunicorn.
        """
        # getting the resource App
        app = self.setup_app()
        return app
