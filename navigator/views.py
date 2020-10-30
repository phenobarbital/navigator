import asyncio
import datetime
import inspect
import json
import logging
import traceback
from abc import ABC, ABCMeta, abstractmethod, abstractproperty
from functools import partial
from logging.config import dictConfig
from typing import Any, Callable, Dict, List, Optional
from urllib import parse

import aiohttp_cors
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web import Response, StreamResponse
from aiohttp.web_exceptions import (
    HTTPClientError,
    HTTPInternalServerError,
    HTTPMethodNotAllowed,
    HTTPNoContent,
    HTTPNotImplemented,
    HTTPUnauthorized,
)
from aiohttp_cors import CorsViewMixin
from asyncdb.providers.memcache import memcache
from settings.settings import MEMCACHE_HOST, MEMCACHE_PORT, logging_config, loglevel

from navigator.libs.encoders import DefaultEncoder

dictConfig(logging_config)


class BaseHandler(CorsViewMixin):
    _config = None
    _mem = None
    _now = None
    _loop = None
    logger: logging.Logger
    _lasterr = None

    cors_config = {
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            allow_headers="*",
        )
    }

    def __init__(self, *args, **kwargs):
        CorsViewMixin.__init__(self)
        self._now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        self._loop = asyncio.get_event_loop()
        self.logger = logging.getLogger("Navigator")
        self.logger.setLevel(loglevel)
        self.post_init(self, *args, **kwargs)

    def post_init(self, *args, **kwargs):
        pass

    def now(self):
        return self._now

    def log(self, message: str):
        self.logger.info(message)

    # function returns
    def no_content(
        self, request, headers, content_type: str = "application/json"
    ) -> web.Response:
        response = HTTPNoContent(content_type=content_type)
        response.headers["Pragma"] = "no-cache"
        for header, value in headers.items():
            response.headers[header] = value
        return response

    def response(
        self,
        request: web.Request,
        response: str = "",
        state: int = 200,
        headers: dict = {},
        **kwargs
    ) -> web.Response:
        args = {"status": state, "content_type": "application/json", **kwargs}
        if isinstance(response, dict):
            args["text"] = json.dumps(response, cls=DefaultEncoder)
        else:
            args["body"] = response
        obj = web.Response(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        return obj

    def json_response(self, response={}, headers={}, state=200, encoder=None):
        if encoder is not None:
            if inspect.isclass(encoder):
                # its a class-based Encoder
                jsonfn = partial(json.dumps, cls=encoder)
            else:
                # its a function
                jsonfn = partial(json.dumps, default=encoder)
        else:
            jsonfn = json.dumps
        obj = web.json_response(response, status=state, dumps=jsonfn)
        for header, value in headers.items():
            obj.headers[header] = value
        return obj

    def critical(
        self,
        request: web.Request,
        exception: Exception = None,
        traceback=None,
        state: int = 500,
        headers: dict = {},
        **kwargs
    ) -> web.Response:
        # TODO: process the exception object
        response_obj = {
            "status": "Failed",
            "reason": str(exception),
            "stacktrace": traceback,
        }
        args = {
            "text": json.dumps(response_obj),
            "reason": "Server Error",
            "content_type": "application/json",
            **kwargs,
        }
        if state == 500:  # bad request
            obj = HTTPInternalServerError(**args)
        else:
            obj = HTTPServerError(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        return obj

    def error(
        self,
        request: dict,
        response: dict = {},
        exception: Exception = None,
        state: int = 400,
        headers: dict = {},
        **kwargs
    ) -> web.Response:
        # TODO: process the exception object
        response_obj = {"status": "Failed"}
        if exception:
            response_obj["reason"] = str(exception)
        args = {**kwargs}
        if isinstance(response, dict):
            response_obj = {**response_obj, **response}
            args["content_type"] = "application/json"
            args["text"] = json.dumps(response_obj, cls=DefaultEncoder)
        else:
            args["body"] = response
        # defining the error
        if state == 400:  # bad request
            obj = web.HTTPBadRequest(**args)
        elif state == 401:  # unauthorized
            obj = web.HTTPUnauthorized(**args)
        elif state == 403:  # forbidden
            obj = web.HTTPForbidden(**args)
        elif state == 404:  # not found
            obj = web.HTTPNotFound(**args)
        else:
            obj = web.HTTPClientError(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        return obj

    def not_implemented(
        self, request: web.Request, response: dict = {}, headers: dict = {}, **kwargs
    ) -> web.Response:
        args = {
            "text": json.dumps(response),
            "reason": "Method not Implemented",
            "content_type": "application/json",
            **kwargs,
        }
        response = HTTPNotImplemented(**args)
        for header, value in headers.items():
            response.headers[header] = value
        return response

    def not_allowed(
        self,
        request: web.Request,
        response: dict = {},
        headers: dict = {},
        allowed: dict = {},
        **kwargs
    ) -> web.Response:
        if not allowed:
            allow = self._allowed
        else:
            allow = allowed
        args = {
            "method": request.method,
            "text": json.dumps(response),
            "reason": "Method not Allowed",
            "content_type": "application/json",
            "allowed_methods": allow,
            **kwargs,
        }
        if allowed:
            headers["Allow"] = ",".join(allow)
        else:
            headers["Allow"] = ",".join(allow)
        obj = HTTPMethodNotAllowed(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        return obj

    def query_parameters(self, request: web.Request) -> dict:
        return {key: val for (key, val) in request.query.items()}

    async def body(self, request: web.Request) -> str:
        body = None
        try:
            if request.body_exists:
                body = await request.read()
                body = body.decode("ascii")
        except Exception as e:
            pass
        finally:
            return body

    async def json_data(self, request):
        return await request.json()


class BaseView(web.View, BaseHandler, AbstractView):
    # _allowed: FrozenSet = frozenset()  # {'get', 'post', 'put', 'patch', 'delete', 'option'}

    def __init__(self, request, *args, **kwargs):
        AbstractView.__init__(self, request)
        BaseHandler.__init__(self, *args, **kwargs)
        self._request = request

    def get_args(self) -> dict:
        args = {}
        for arg in self.request.match_info:
            try:
                val = self.request.match_info.get(arg)
                object.__setattr__(self, arg, val)
                args[arg] = val
            except AttributeError:
                pass
        qry = {}
        try:
            qry = {key: val for (key, val) in self.request.rel_url.query.items()}
        except Exception as err:
            print(err)
            pass
        args = {**args, **qry}
        return args

    async def post_data(self) -> dict:
        args = {}
        if self.request.headers.get("Content-Type") == "application/json":
            return await self.request.json()
        try:
            args = await self.request.post()
            if not args or len(args) == 0:
                if self.request.body_exists:
                    body = await self.request.read()
                    body = body.decode("ascii")
                    if body:
                        try:
                            args = dict(
                                (k, v if len(v) > 1 else v[0])
                                for k, v in parse.parse_qs(body).items()
                            )
                        except (KeyError, ValueError):
                            pass
        finally:
            print(args)
            return args

    def no_content(self, headers: Dict) -> web.Response:
        response = HTTPNoContent(content_type="application/json")
        response.headers["Pragma"] = "no-cache"
        for header, value in headers.items():
            response.headers[header] = value
        return response


class DataView(BaseView):
    _mcache: Any = None
    _connection: Any = None
    _redis: Any = None

    def post_init(self, *args, **kwargs):
        mem_params = {"host": MEMCACHE_HOST, "port": MEMCACHE_PORT}
        self._mcache = memcache(params=mem_params)

    async def connection(self):
        return self._connection

    async def connect(self, request):
        await self._mcache.connection()
        self._connection = await request.app["pool"].acquire()
        self._redis = request.app["redis"]

    async def close(self):
        if self._mcache and self._mcache.is_connected():
            await self._mcache.close()
            self._mcache = None
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def asyncdb(self, request):
        db = None
        try:
            pool = request.app["pool"]
            if pool.is_connected():
                conn = await pool.acquire()
                db = asyncORM(db=conn, loop=self._loop)
                return db
        finally:
            return db

    async def query(self, sql):
        result = None
        if self._connection:
            try:
                result, error = await self._connection.query(sql)
                if error:
                    print(error)
                    result = None
                    self._lasterr = error
            except Exception as err:
                print(err)
                result = None
                self._lasterr = err
            finally:
                return result

    async def queryrow(self, sql):
        result = None
        if self._connection:
            try:
                result, error = await self._connection.queryrow(sql)
                if error:
                    result = None
            except Exception as err:
                print(err)
            finally:
                return result

    async def execute(self, sql):
        result = None
        if self._connection:
            try:
                result, error = await self._connection.execute(sql)
                if error:
                    result = None
            except Exception as err:
                print(err)
            finally:
                return result

    """
    Meta-Operations
    """

    def table(self, table):
        try:
            return self._query_raw.format_map(SafeDict(table=table))
        except Exception as e:
            print(e)
            return False

    def fields(self, sentence, fields=None):
        _sql = False
        if not fields:
            _sql = sentence.format_map(SafeDict(fields="*"))
        elif type(fields) == str:
            _sql = sentence.format_map(SafeDict(fields=fields))
        elif type(fields) == list:
            _sql = sentence.format_map(SafeDict(fields=",".join(fields)))
        return _sql

    """
    where
      add WHERE conditions to SQL
    """

    def where(self, sentence, where):
        sql = ""
        if sentence:
            where_string = ""
            if not where:
                sql = sentence.format_map(SafeDict(where_cond=""))
            elif type(where) == dict:
                where_cond = []
                for key, value in where.items():
                    # print("KEY {}, VAL: {}".format(key, value))
                    if type(value) == str or type(value) == int:
                        if value == "null" or value == "NULL":
                            where_string.append("%s IS NULL" % (key))
                        elif value == "!null" or value == "!NULL":
                            where_string.append("%s IS NOT NULL" % (key))
                        elif key.endswith("!"):
                            where_cond.append("%s != %s" % (key[:-1], value))
                        else:
                            if (
                                type(value) == str
                                and value.startswith("'")
                                and value.endswith("'")
                            ):
                                where_cond.append("%s = %s" % (key, "{}".format(value)))
                            elif type(value) == int:
                                where_cond.append("%s = %s" % (key, "{}".format(value)))
                            else:
                                where_cond.append(
                                    "%s = %s" % (key, "'{}'".format(value))
                                )
                    elif type(value) == bool:
                        val = str(value)
                        where_cond.append("%s = %s" % (key, val))
                    else:
                        val = ",".join(map(str, value))
                        if type(val) == str and "'" not in val:
                            where_cond.append("%s IN (%s)" % (key, "'{}'".format(val)))
                        else:
                            where_cond.append("%s IN (%s)" % (key, val))
                # if 'WHERE ' in sentence:
                #    where_string = ' AND %s' % (' AND '.join(where_cond))
                # else:
                where_string = " WHERE %s" % (" AND ".join(where_cond))
                print("WHERE cond is %s" % where_string)
                sql = sentence.format_map(SafeDict(where_cond=where_string))
            elif type(where) == str:
                where_string = where
                if not where.startswith("WHERE"):
                    where_string = " WHERE %s" % where
                sql = sentence.format_map(SafeDict(where_cond=where_string))
            else:
                sql = sentence.format_map(SafeDict(where_cond=""))
            del where
            del where_string
            return sql
        else:
            return False

    def limit(self, sentence, limit=1):
        """
        LIMIT
          add limiting to SQL
        """
        if sentence:
            return "{q} LIMIT {limit}".format(q=sentence, limit=limit)
        return self

    def orderby(self, sentence, ordering=[]):
        """
        LIMIT
          add limiting to SQL
        """
        if sentence:
            if type(ordering) == str:
                return "{q} ORDER BY {ordering}".format(q=sentence, ordering=ordering)
            elif type(ordering) == list:
                return "{q} ORDER BY {ordering}".format(
                    q=sentence, ordering=", ".join(ordering)
                )
        return self
