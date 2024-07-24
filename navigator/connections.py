"""Connection Manager for Navigator."""
import asyncio
import logging
from typing import Optional
from collections.abc import Callable
from asyncdb import AsyncPool, AsyncDB
from asyncdb.exceptions import ProviderError, DriverError
from .types import WebApp
from .conf import (
    default_dsn,
    DB_TIMEOUT,
    DB_STATEMENT_TIMEOUT,
    DB_KEEPALIVE_IDLE
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
        name: str = "database",
        params: dict = None,
        init: Callable = None,
        startup: Callable = None,
        shutdown: Callable = None,
        **kwargs,
    ):
        self.driver = driver
        self.name = name
        self.params = params if params else {}
        self.kwargs = kwargs
        self._dsn = dsn if dsn is not None else default_dsn
        if init:
            self._init = init
        if startup:
            self._startup_ = startup
        if shutdown:
            self._shutdown_ = shutdown
        # Empty Connection:
        self.timeout = kwargs.pop("timeout", DB_TIMEOUT)
        self.conn: Callable = None
        if self._init_:
            self.conn.setup_func = self._init_

    def connection(self):
        return self.conn

    def configure(self, app: WebApp, register: str = "database") -> None:
        """configure.
        Configure Connection Handler to connect on App initialization.
        """
        self._register = register
        app.on_startup.append(self.startup)
        app.on_shutdown.append(self.shutdown)
        app.on_cleanup.append(self.cleanup)

    def is_connected(self) -> bool:
        return bool(self.conn.is_connected())

    async def cleanup(self, app: WebApp):
        pass

    async def startup(self, app: WebApp) -> None:
        try:
            main_app = app["Main"]
            db = main_app[self._register]
            if self._dsn == db._dsn:
                logging.debug(
                    f"There is already a connection enabled on {app!r}"
                )
                self.conn = db
                app[self._register] = self.conn
                # any callable will be launch on connection startup.
                if callable(self._startup_):
                    await self._startup_(app, self.conn)
                return
        except (TypeError, KeyError):
            pass
        if "database" in app or self._register in app:
            # there is already a connection enabled to this Class:
            logging.debug(f"There is already a connection enabled on {app!r}")
            # any callable will be launch on connection startup.
            if callable(self._startup_):
                await self._startup_(app, self.conn)
            return
        logging.debug(f"Starting DB {self.driver} connection on App: {self.name}")
        if self.timeout is None:
            self.timeout = 360000
        try:
            if self.pool_based:
                self.conn = AsyncPool(
                    self.driver,
                    dsn=self._dsn,
                    params=self.params,
                    timeout=int(self.timeout),
                    **self.kwargs,
                )
                await self.conn.connect()
            else:
                self.conn = AsyncDB(
                    self.driver,
                    dsn=self._dsn,
                    params=self.params,
                    timeout=int(self.timeout),
                    **self.kwargs,
                )
                await self.conn.connection()
            ### register in app the connector:
            app[self._register] = self.conn
            # any callable will be launch on connection startup.
            if callable(self._startup_):
                await self._startup_(app, self.conn)
        except (ProviderError, DriverError) as ex:
            raise RuntimeError(f"Error creating DB {self.driver}: {ex}") from ex

    async def shutdown(self, app: WebApp) -> None:
        logging.debug(f"Closing DB connection on App: {app!r}")
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
    timeout: int = 60
    statement_timeout: int = 3600

    def __init__(
        self,
        name: str = "",
        dsn: str = '',
        init: Optional[Callable] = None,
        startup: Optional[Callable] = None,
        shutdown: Optional[Callable] = None,
        evt: asyncio.AbstractEventLoop = None,
        **kwargs,
    ):
        if "statement_timeout" in kwargs:
            self.statement_timeout = kwargs["statement_timeout"]
        else:
            self.statement_timeout = DB_STATEMENT_TIMEOUT
        kwargs = {
            "min_size": 2,
            "server_settings": {
                "application_name": name,
                "client_min_messages": "notice",
                "jit": "on",
                "jit_above_cost": "10000000",
                "effective_cache_size": "2147483647"
            },
        }
        super(PostgresPool, self).__init__(
            driver=self.driver,
            dsn=dsn,
            name=name,
            init=init,
            startup=startup,
            shutdown=shutdown,
            evt=evt,
            **kwargs,
        )
        # self._dsn = default_dsn

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
        **kwargs,
    ):
        super(RedisPool, self).__init__(
            driver=self.driver,
            dsn=dsn,
            init=init,
            startup=startup,
            shutdown=shutdown,
            evt=evt,
            **kwargs,
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
            logging.debug("Exiting Redis ...")
