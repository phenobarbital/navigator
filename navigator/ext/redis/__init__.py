"""Redis Extension.
Redis connection on any Application.
"""
from navigator.ext.db import DBConnection
from navigator.types import WebApp
from navigator.conf import CACHE_URL


class RedisConnection(DBConnection):
    """RedisConnection.

    Description: NAV extension for adding Redis (aioredis) capabilities.

    Args:
        app_name (str): Name of the current Extension, will use it to save it into aiohttp Application.
        dsn (str): default DSN (if none, use default.)

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: aioredis is not installed.

    Returns:
        RedisConnection: a Redis connection will be added to Web Application.
    """
    name: str = 'redis'
    app: WebApp = None
    driver: str = 'redis'
    timeout: int = 10

    def __init__(
            self,
            app_name: str = None,
            dsn: str = None,
            **kwargs
        ) -> None:
        self._dsn: str = None
        super(RedisConnection, self).__init__(
            app_name=app_name,
            driver='redis',
            dsn=dsn,
            **kwargs
        )
        if not self._dsn:
            self._dsn = CACHE_URL
