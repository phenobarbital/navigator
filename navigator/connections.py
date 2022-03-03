"""Connection Manager for Navigator."""

import logging
from multiprocessing.connection import wait
from aiohttp import web
from asyncdb import AsyncPool, AsyncDB
from typing import (
    Dict,
    List,
    Callable,
    Optional,
    Iterable
)
try:
    from settings.settings import TIMEZONE
except ImportError:
    # Timezone (For parsedate)
    TIMEZONE = "America/New_York"


class AbstractConnection(object):
    pool_based: bool = True
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
        if self._init:
            self.conn.setup_func = self._init

    def connection(self):
        return self.conn

    def configure(self, app: web.Application):
        app.on_startup.append(
            self.startup
        )
        app.on_shutdown.append(
            self.shutdown
        )
        app.on_cleanup.append(
            self.cleanup
        )
        

    def is_connected(self):
        return bool(self.conn.is_connected())
    
    async def cleanup(self, app: web.Application):
        pass

    async def startup(self, app: web.Application):
        if self.pool_based:
            await self.conn.connect()
        else:
            await self.conn.connection()
        if self._startup: # any callable will be launch on connection startup.
            await self._startup(self.conn)

    async def shutdown(self, app: web.Application):
        if self._shutdown:
            await self._shutdown(self.conn)
        logging.debug(" === Closing all connections === ")
        try:
            await self.conn.close()
        finally:
            logging.debug("Exiting ...")
        
        
class PostgresPool(AbstractConnection):
    driver: str = "pg"
    pool_based: bool = True
    timeout: int = 3600

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
                "statement_timeout": "60",
                "effective_cache_size": "2147483647"
            },
        }
        super(PostgresPool, self).__init__(self.driver, dsn, name, init, startup, shutdown, **kwargs)

    async def shutdown(self, app: web.Application):
        if self._shutdown:
            await self._shutdown(self.conn)
        logging.debug(" === Closing all connections === ")
        try:
            await self.conn.wait_close(gracefully=True, timeout=2)
        finally:
            logging.debug("Exiting ...")

class RedisPool(AbstractConnection):
    driver: str = "redis"
    pool_based: bool = True
    timeout: int = 60

    def __init__(
        self,
        dsn: str,
        name: str = "",
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        **kwargs
    ):
        super(RedisPool, self).__init__(
            self.driver, dsn, name, init, startup, shutdown, **kwargs
        )
        
    async def shutdown(self, app: web.Application):
        pass

    async def cleanup(self, app: web.Application):
        if self._shutdown:
            await self._shutdown(self.conn)
        logging.debug(" === Closing REDIS === ")
        try:
            await self.conn.close()
        finally:
            logging.debug("Exiting ...")