"""Redis Extension.
Redis connection on any Application.
"""
from ...extensions import BaseExtension
from ...exceptions import NavException
from ...types import WebApp
from ...conf import MEMCACHE_HOST, MEMCACHE_PORT

try:
    import aiomcache
    from aiomcache.exceptions import ClientException
except ImportError as ex:
    raise RuntimeError("Memcache Extension: aiomcache is not installed.") from ex


class Memcache(BaseExtension):
    """Memcache.

    Description: NAV extension for adding a Memcache connection (based on aiomecache).

    Args:
        app_name (str): Name of the current Extension, will use it to save it into aiohttp Application.
        host: (str): Optional host to the connection, if none, will use default.
        port: (int): Optiona port of the connection, if none, will use default.

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: aiomecache is not installed.

    Returns:
        Memcache: a Memcache connection will be added to Web Application.
    """

    name: str = "memcache"
    app: WebApp = None
    timeout: int = 10

    def __init__(
        self, app_name: str = None, host: str = None, port: int = None, **kwargs
    ) -> None:
        self.conn = None
        super(Memcache, self).__init__(app_name=app_name, **kwargs)
        self.host = host
        if not self.host:
            self.host = MEMCACHE_HOST
        self.port = port
        if not self.port:
            self.port = MEMCACHE_PORT

    async def on_context(self, app: WebApp):
        ## making the connection:
        try:
            self.conn = aiomcache.Client(self.host, self.port, **self._kwargs)
        except aiomcache.exceptions.ValidationException as err:
            raise NavException(f"Invalid Connection Parameters: {err}") from err
        except ClientException as err:
            raise NavException(f"Unable to connect to Memcache: {err}") from err
        yield  # yielding the context.
        try:
            await self.conn.close()
            del self.conn
        except ClientException as err:
            raise NavException(f"Unable to close Memcache connection: {err}") from err

    def get_connection(self):
        return self.conn

    async def set(self, key, value, timeout: int = None):
        try:
            args = {}
            if timeout:
                args = {"exptime": timeout}
            return await self.conn.set(
                bytes(key, "utf-8"), bytes(value, "utf-8"), **args
            )
        except ClientException as err:
            raise NavException(f"Set Memcache Error: {err}") from err
        except Exception as err:
            raise NavException(f"Memcache Unknown Error: {err}") from err

    async def get(self, key):
        try:
            result = await self.conn.get(bytes(key, "utf-8"))
            if result:
                return result.decode("utf-8")
            else:
                return None
        except ClientException as err:
            raise NavException(f"Get Memcache Error: {err}") from err
        except Exception as err:
            raise NavException(f"Memcache Unknown Error: {err}") from err

    async def delete(self, key):
        try:
            return await self.conn.delete(
                key=bytes(key, "utf-8")
            )  # pylint: disable=E1120
        except ClientException as err:
            raise NavException(f"Delete Memcache Error: {err}") from err
        except Exception as err:
            raise NavException(f"Memcache Unknown Error: {err}") from err
