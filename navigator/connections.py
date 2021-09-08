"""Connection Manager for Navigator."""

import logging
import json
import uuid
from asyncpg.pgproto import pgproto
from asyncdb.utils.encoders import BaseEncoder
from asyncdb import AsyncPool
from asyncdb.providers import BasePool, BaseProvider
from typing import Dict, List, Callable, Optional, Iterable

try:
    from settings.settings import TIMEZONE
except ImportError:
    # Timezone (For parsedate)
    TIMEZONE = "America/New_York"


class AbstractConnection(object):
    driver: str = "pg"
    pool_based: bool = True
    _loop = None
    timeout: int = 60
    _init: Callable = None
    _startup: Callable = None
    _shutdown: Callable = None

    def __init__(
        self,
        driver: str = "pg",
        dsn: str = "",
        name: str = "",
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        **kwargs
    ):
        self.driver = driver
        if "loop" in kwargs:
            self._loop = kwargs["loop"]
            del kwargs["loop"]
        if init:
            self._init = init
        if startup:
            self._startup = startup
        if shutdown:
            self._shutdown = shutdown

        if self.pool_based:
            self.conn = AsyncPool(self.driver, dsn=dsn, timeout=self.timeout, **kwargs)
        else:
            self.conn = AsyncDB(self.driver, dsn=dsn, timeout=self.timeout, **kwargs)
        # configure connection
        self.configure()

    def connection(self):
        return self.conn

    def configure(self):
        if self._init and self.pool_based:
            self.conn.setup_func = self._init

    def is_connected(self):
        return bool(self._connected)

    async def startup(self, **kwargs):
        if "app" in kwargs:
            app = kwargs["app"]
            if app is not None:
                if "database" in app:
                    # re-use the database connection
                    self.conn = app["database"]
        if self.pool_based:
            await self.conn.connect()
        else:
            await self.conn.connection()
        if self._startup:
            await self._startup(self.conn, **kwargs)
        self._connected = True

    async def shutdown(self, **kwargs):
        if self._shutdown:
            await self._shutdown(self.conn, **kwargs)
        logging.debug("Closing all connections")
        if self.pool_based:
            logging.debug("Closing DB Pool")
            await self.conn.wait_close(gracefully=False, timeout=5)
        else:
            await self.conn.close()
        logging.debug("Exiting ...")


class PostgresPool(AbstractConnection):
    driver: str = "pg"
    pool_based: bool = True
    timeout: int = 360000

    def __init__(
        self,
        dsn: str,
        name: str = "",
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        **kwargs
    ):
        kwargs = {
            "min_size": 5,
            "server_settings": {
                "application_name": name,
                "client_min_messages": "notice",
                "max_parallel_workers": "48",
                "jit": "off",
                "statement_timeout": "3600000",
                "effective_cache_size": "2147483647"
            },
        }
        if "loop" in kwargs:
            self._loop = kwargs["loop"]
            del kwargs["loop"]
        if init:
            self._init = init
        if startup:
            self._startup = startup
        if shutdown:
            self._shutdown = shutdown

        self.conn = AsyncPool(
            self.driver,
            dsn=dsn,
            timeout=self.timeout,
            **kwargs
        )
        # passing the configuration
        self.conn.setup_func = self.configure

    async def configure(self, conn):
        # also, if exists this init connection, run
        if self._init:
            await self._init(conn)
