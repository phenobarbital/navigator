from asyncdb import AsyncDB
from asyncdb.exceptions import DriverError, NoDataFound
from ..exceptions import NavException
from .base import BaseView

class DataView(BaseView):
    async def asyncdb(self, driver: str = "pg", dsn: str = None, params: dict = None):
        try:
            conn = None
            try:
                db = self.request.app["database"]
                conn = await db.acquire()
            except KeyError:
                if params:
                    args = {"params": params}
                else:
                    args = {"dsn": dsn}
                # getting database connection directly:
                db = AsyncDB(driver, **args)
                conn = await db.connection()
            return conn
        except DriverError as ex:
            raise NavException(
                f"Error connecting to DB: {ex}"
            ) from ex
        except Exception as err:
            raise NavException(
                f"Error connecting to DB: {err}"
            ) from err

    async def query(self, sql):
        result = None
        if self._connection:
            self._lasterr = None
            try:
                result, error = await self._connection.query(sql)
                if error:
                    print(error)
                    result = None
                    self._lasterr = error
            except DriverError as err:
                print(err)
                result = None
                self._lasterr = err
            finally:
                return result  # pylint: disable=W0150

    async def queryrow(self, sql):
        result = None
        if self._connection:
            self._lasterr = None
            try:
                result, error = await self._connection.queryrow(sql)
                if error:
                    result = None
                    self._lasterr = error
            except NoDataFound:
                raise
            except DriverError as ex:
                self._lasterr = ex
            except Exception as err:
                self._lasterr = err
                raise NavException(
                    f"Error connecting to DB: {err}"
                ) from err
            finally:
                return result  # pylint: disable=W0150

    async def execute(self, sql):
        result = None
        if self._connection:
            self._lasterr = None
            try:
                result, error = await self._connection.execute(sql)
                if error:
                    result = None
                    self._lasterr = error
            except NoDataFound:
                self._lasterr = None
            except DriverError as ex:
                self._lasterr = ex
            except Exception as err:
                self._lasterr = err
                raise NavException(
                    f"Error connecting to DB: {err}"
                ) from err
            finally:
                return result  # pylint: disable=W0150
