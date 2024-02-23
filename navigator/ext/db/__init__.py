"""DB (asyncdb) Extension.
DB connection for any Application.
"""
from collections.abc import Callable
from navconfig.logging import logging
from asyncdb import AsyncDB
from asyncdb.exceptions import ProviderError, DriverError
from ...types import WebApp
from ...extensions import BaseExtension
from ...exceptions import NavException, ConfigError


class DBConnection(BaseExtension):
    """DBConnection.

    Description: NAV extension for any DB (asyncdb) connection.

    Args:
        app_name (str): Name of the current connection, will use it to save it into aiohttp Application.
        dsn (str): default DSN (if none, use default.)
        params (dict): optional connection parameters (if DSN is none)

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: Database connector is not installed.

    Returns:
        DBConnection: a DB connection will be added to Web Application.
    """

    name: str = "asyncdb"
    app: WebApp = None
    driver: str = "pg"
    timeout: int = 10

    def __init__(
        self, app_name: str = None, driver: str = "pg", dsn: str = None, **kwargs
    ) -> None:
        self.driver = driver
        try:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        except KeyError:
            pass
        try:
            self.params = kwargs["params"]
            del kwargs["params"]
        except KeyError:
            self.params = {}
        super(DBConnection, self).__init__(app_name=app_name, **kwargs)
        self.conn: Callable = None
        self._dsn: str = dsn
        if not self._dsn and not self.params:
            raise ConfigError("DB: No DSN or Parameters for DB connection.")

    async def on_startup(self, app: WebApp):
        """
        Some Authentication backends need to call an Startup.
        """
        try:
            self.conn = AsyncDB(
                self.driver,
                dsn=self._dsn,
                params=self.params,
                timeout=self.timeout,
                **self._kwargs,
            )
            await self.conn.connection()
            ### register redis into app:
            app[self.name] = self.conn
        except (ProviderError, DriverError) as err:
            logging.exception(f"Error on Startup {self.name} Backend: {err!s}")
            raise NavException(
                f"Error on Startup {self.name} Backend: {err!s}"
            ) from err

    async def on_cleanup(self, app: WebApp):
        try:
            await self.conn.close()
        except ProviderError as err:
            raise NavException(
                f"Error on Closing Connection {self.name}: {err!s}"
            ) from err
