"""Connection Manager for Navigator."""
import asyncio
import logging
from typing import (
    Optional
)
from collections.abc import Callable
from asyncdb import AsyncPool, AsyncDB
from asyncdb.exceptions import ProviderError, DriverError
from navigator.types import (
    WebApp
)
from navigator.conf import (
    default_dsn
)

class ConnectionHandler:
    pool_based: bool = True
    timeout: int = 60
    _init_: Optional[Callable] = None
    _startup_: Optional[Callable] = None
    _shutdown_: Optional[Callable] = None

    def __init__(
        self,
        driver: str = "pg",
        dsn: str = "",
        name: str = 'database',
        params: dict = None,
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        **kwargs
    ):
        self.driver = driver
        self.name = name
        self.params = params
        self.kwargs = kwargs
        self._dsn = dsn
        if init:
            self._init = init
        if startup:
            self._startup_ = startup
        if shutdown:
            self._shutdown_ = shutdown
        if self._init_:
            self.conn.setup_func = self._init_
        # Empty Connection:
        self.conn: Callable = None

    def connection(self):
        return self.conn

    def configure(self, app: WebApp, register: str = 'database') -> None:
        """configure.
        Configure Connection Handler to connect on App initialization.
        """
        self._register = register
        app.on_startup.append(
            self.startup
        )
        app.on_shutdown.append(
            self.shutdown
        )
        app.on_cleanup.append(
            self.cleanup
        )

    def is_connected(self) -> bool:
        return bool(self.conn.is_connected())

    async def cleanup(self, app: WebApp):
        pass

    async def startup(self, app: WebApp) -> None:
        if 'database' in app:
            # there is already a connection enabled to this Class:
            logging.debug(f'There is already a connection enabled on {app!r}')
            # any callable will be launch on connection startup.
            if callable(self._startup_):
                await self._startup_(app, self.conn)
            return
        logging.debug(f'Starting DB {self.driver} connection on App: {app!r}')
        try:
            if self.pool_based:
                self.conn = AsyncPool(
                    self.driver,
                    dsn=self._dsn,
                    params=self.params,
                    timeout=self.timeout,
                    **self.kwargs
                )
                await self.conn.connect()
            else:
                self.conn = AsyncDB(
                    self.driver,
                    dsn=self._dsn,
                    params=self.params,
                    timeout=self.timeout,
                    **self.kwargs
                )
                await self.conn.connection()
            ### register in app the connector:
            app[self._register] = self.conn
            # any callable will be launch on connection startup.
            if callable(self._startup_):
                await self._startup_(app, self.conn)
        except (ProviderError, DriverError) as ex:
            raise RuntimeError(
                f"Error creating DB {self.driver}: {ex}"
            ) from ex

    async def shutdown(self, app: WebApp) -> None:
        logging.debug(f'Closing DB connection on App: {app!r}')
        if callable(self._shutdown_):
            await self._shutdown_(app, self.conn)
        logging.debug(" === Closing all connections === ")
        try:
            await self.conn.close()
        finally:
            app[self._register] = None
            logging.debug("Exiting ...")


class PostgresPool(ConnectionHandler):
    driver: str = "pg"
    pool_based: bool = True
    timeout: int = 3600

    def __init__(
        self,
        name: str = "",
        init: Optional[Callable] = None,
        startup: Optional[Callable] = None,
        shutdown: Optional[Callable] = None,
        evt: asyncio.AbstractEventLoop = None,
        **kwargs
    ):
        kwargs = {
            "min_size": 5,
            "server_settings": {
                "application_name": name,
                "client_min_messages": "notice",
                "max_parallel_workers": "48",
                "jit": "off",
                "statement_timeout": "36000",
                "idle_in_transaction_session_timeout": '5min',
                "effective_cache_size": "2147483647"
            },
        }
        super(PostgresPool, self).__init__(
            driver=self.driver,
            name=name,
            init=init,
            startup=startup,
            shutdown=shutdown,
            evt=evt,
            **kwargs
        )
        self._dsn = default_dsn

    async def shutdown(self, app: WebApp):
        if callable(self._shutdown_):
            await self._shutdown_(app, self.conn)
        logging.debug(" === Closing all connections === ")
        try:
            if self.conn:
                await self.conn.wait_close(gracefully=True, timeout=2)
        finally:
            logging.debug("Exiting ...")

class RedisPool(ConnectionHandler):
    driver: str = "redis"
    pool_based: bool = True
    timeout: int = 60

    def __init__(
        self,
        dsn: str,
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        evt: asyncio.AbstractEventLoop = None,
        **kwargs
    ):
        super(RedisPool, self).__init__(
            driver=self.driver,
            dsn=dsn,
            init=init,
            startup=startup,
            shutdown=shutdown,
            evt=evt,
            **kwargs
        )

    async def shutdown(self, app: WebApp):
        pass

    async def cleanup(self, app: WebApp):
        if callable(self._shutdown_):
            await self._shutdown_(app, self.conn)
        logging.debug(" === Closing REDIS === ")
        try:
            await self.conn.close()
        finally:
            logging.debug("Exiting ...")
