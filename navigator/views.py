import asyncio
import datetime
import traceback
from typing import Any, Optional, Union
from collections.abc import Callable
from urllib import parse
from dataclasses import dataclass

from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web_exceptions import (
    HTTPMethodNotAllowed,
    HTTPNoContent,
    HTTPNotImplemented,
)
import orjson
from orjson import JSONDecodeError
import aiohttp_cors
from aiohttp_cors import CorsViewMixin
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from asyncdb import AsyncDB
from asyncdb.models import Model
from asyncdb.exceptions import ProviderError, DriverError, NoDataFound
from navconfig.logging import logging, loglevel
from navigator_session import get_session
from navigator.exceptions import NavException, InvalidArgument
from navigator.libs.json import JSONContent, json_encoder, json_decoder
from navigator.responses import JSONResponse


DEFAULT_JSON_ENCODER = json_encoder
DEFAULT_JSON_DECODER = json_decoder


class BaseHandler(CorsViewMixin):
    _config = None
    _mem = None
    _now = None
    _loop = None
    _logger_name: str = "navigator"
    _lasterr = None
    _allowed = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

    cors_config = {
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_methods="*",
            allow_headers="*",
            max_age=3600,
        )
    }

    def __init__(self, *args, **kwargs):
        CorsViewMixin.__init__(self)
        self._now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        self._loop = asyncio.get_event_loop()
        self._json: Callable = JSONContent()
        self.logger: logging.Logger = None
        self.post_init(self, *args, **kwargs)

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)
        self.logger.setLevel(loglevel)

    def now(self):
        return self._now

    def log(self, message: str):
        self.logger.info(message)

    # function returns
    def no_content(
        self,
        headers: dict = None,
        content_type: str = "application/json",
    ) -> web.Response:
        if not headers:
            headers = {}
        response = HTTPNoContent(content_type=content_type)
        response.headers["Pragma"] = "no-cache"
        for header, value in headers.items():
            response.headers[header] = value
        return response

    def response(
        self,
        response: Union[str, dict] = "",
        status: int = 200,
        state: int = None,
        headers: dict = None,
        content_type: str = "application/json",
        **kwargs,  # pylint: disable=W0613
    ) -> web.Response:
        if not headers:  # TODO: set to default headers.
            headers = {}
        if state is not None:  # backward compatibility
            status = state
        args = {"status": status, "content_type": content_type, "headers": headers}
        if isinstance(response, dict):
            args["text"] = self._json.dumps(response)
        else:
            args["body"] = response
        return web.Response(**args)

    def json_response(
        self,
        response: dict = None,
        reason: str = None,
        headers: dict = None,
        status: int = 200,
        state: int = None,
        cls: Callable = None,
    ):
        """json_response.

        Return a JSON-based Web Response.
        """
        if state is not None:  # backward compatibility
            status = state
        if cls:
            logging.warning("Passing *cls* attribute is deprecated for json_response.")
        if not headers:  # TODO: set to default headers.
            headers = {}
        return JSONResponse(response, status=status, headers=headers, reason=reason)

    def critical(
        self,
        reason: str = None,
        exception: Exception = None,
        stacktrace: str = None,
        status: int = 500,
        state: int = None,
        headers: dict = None,
        content_type: str = "application/json",
        **kwargs,  # pylint: disable=W0613
    ) -> web.Response:
        # TODO: process the exception object
        if not headers:  # TODO: set to default headers.
            headers = {}
        if state is not None:  # backward compatibility
            status = state
        response_obj = {
            "message": reason if reason else "Failed",
            "error": str(exception),
            "stacktrace": stacktrace,
        }
        args = {
            "text": self._json.dumps(response_obj),
            "reason": "Server Error",
            "content_type": content_type,
        }
        if status == 500:  # bad request
            obj = web.HTTPInternalServerError(**args)
        else:
            obj = web.HTTPServerError(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        raise obj

    def error(
        self,
        response: dict = None,
        exception: Exception = None,
        status: int = 400,
        state: int = None,
        headers: dict = None,
        content_type: str = "application/json",
        **kwargs,
    ) -> web.Response:
        if not headers:  # TODO: set to default headers.
            headers = {}
        # TODO: process the exception object
        response_obj = {}
        if state is not None:  # backward compatibility
            status = state
        if exception:
            response_obj["reason"] = str(exception)
        args = {"content_type": content_type, **kwargs}
        if isinstance(response, dict):
            response_obj = {**response_obj, **response}
            # args["content_type"] = "application/json"
            args["text"] = self._json.dumps(response_obj)
        else:
            args["body"] = response
        # defining the error
        if status == 400:  # bad request
            obj = web.HTTPBadRequest(**args)
        elif status == 401:  # unauthorized
            obj = web.HTTPUnauthorized(**args)
        elif status == 403:  # forbidden
            obj = web.HTTPForbidden(**args)
        elif status == 404:  # not found
            obj = web.HTTPNotFound(**args)
        elif status == 406:  # Not acceptable
            obj = web.HTTPNotAcceptable(**args)
        elif status == 412:
            obj = web.HTTPPreconditionFailed(**args)
        elif status == 428:
            obj = web.HTTPPreconditionRequired(**args)
        else:
            obj = web.HTTPBadRequest(**args)
        for header, value in headers.items():
            obj.headers[header] = value
        raise obj

    def not_implemented(
        self,
        response: dict = None,
        headers: dict = None,
        content_type: str = "application/json",
        **kwargs,  # pylint: disable=W0613
    ) -> web.Response:
        if not headers:  # TODO: set to default headers.
            headers = {}
        args = {
            "text": self._json.dumps(response),
            "reason": "Method not Implemented",
            "content_type": content_type,
            **kwargs,
        }
        response = HTTPNotImplemented(**args)
        for header, value in headers.items():
            response.headers[header] = value
        raise response

    def not_allowed(
        self,
        request: web.Request = None,
        response: dict = None,
        headers: dict = None,
        allowed: dict = None,
        content_type: str = "application/json",
        **kwargs,
    ) -> web.Response:
        if not headers:  # TODO: set to default headers.
            headers = {}
        if not request:
            request = self.request
        if not allowed:
            allow = self._allowed
        else:
            allow = allowed
        if response is None:
            response = {
                "message": f"Method {request.method} not Allowed.",
                "allowed": allow,
            }
            response = self._json.dumps(response)
        elif isinstance(response, dict):
            response = self._json.dumps(response)
        args = {
            "method": request.method,
            "text": response,
            "reason": "Method not Allowed",
            "content_type": content_type,
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
        raise obj

    def query_parameters(self, request: web.Request) -> dict:
        return {key: val for (key, val) in request.query.items()}

    async def get_json(self, request: web.Request = None) -> Any:
        if not request:
            request = self.request
        try:
            return await request.json(loads=orjson.loads)
        except ValidationError:
            return None
        except Exception as err:  # pylint: disable=W0703
            logging.warning(err)
            return None

    async def body(self, request: web.Request) -> str:
        body = None
        try:
            if request.body_exists:
                body = await request.read()
                body = body.decode("ascii")
        except Exception:  # pylint: disable=W0703
            pass
        finally:
            return body  # pylint: disable=W0150

    async def json_data(self, request: web.Request = None):
        if not request:
            request = self.request
        return await self.get_json(request)

    def match_parameters(self, request: web.Request = None) -> dict:
        params = {}
        if not request:
            request = self.request
        for arg in request.match_info:
            try:
                val = request.match_info.get(arg)
                object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        return params

    def get_arguments(self, request: web.Request = None) -> dict:
        params = {}
        if not request:
            rq = self.request
        else:
            rq = request
        for arg in rq.match_info:
            try:
                val = rq.match_info.get(arg)
                object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        qry = {}
        try:
            qry = {key: val for (key, val) in rq.rel_url.query.items()}
        except (AttributeError, TypeError, ValueError) as err:
            print(err)
        params = {**params, **qry}
        return params

    get_args = get_arguments

    async def data(self, request: web.Request = None) -> dict:
        # only get post Data
        params = {}
        if not request:
            request = self.request
        try:
            params = await self.get_json(request)
        except JSONDecodeError as err:
            logging.debug(f"Invalid POST DATA: {err!s}")
        # if any, mix with match_info data:
        for arg in request.match_info:
            try:
                val = request.match_info.get(arg)
                # object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        return params

    async def validate_handler(
        self, model: dataclass, request: web.Request = None, strict: bool = True
    ) -> Optional[dict]:
        """validate_handler.

        Description: Using a dataclass (or Model) to validate data entered into System.

        Args:
            model (dataclass): Model to be used for validation.
            request (web.Request, optional): Request Handler. Defaults to None.
            strict (bool): if True, Function returns Exceptions on failure, else, None.

        Raises:
            web.HTTPNotAcceptable: Invalid Input.
            web.BadRequest: Model raises a ValidationError.
            web.HTTPNotFound: data is empty or not found.

        Returns:
            Optional[dict]: Data filtered and validated if True.
        """
        data = None
        if not request:
            request = self.request
        # check if data comes from POST or GET:
        if request.method in ("POST", "PUT", "PATCH"):
            # getting data from POST
            data = await request.json(loads=DEFAULT_JSON_DECODER)
        elif request.method == "GET":
            data = {key: val for (key, val) in request.query.items()}
        else:
            return HTTPNotImplemented(
                reason=f"{request.method} Method not Implemented for Data Validation.",
                content_type="application/json",
            )
        if data is None:
            return web.HTTPNotFound(
                reason="There is no content for validation.",
                content_type="application/json",
            )
        # making the validation of data:
        headers = {"X-MODEL": f"{model!s}"}
        args = {"content_type": "application/json"}
        if isinstance(data, dict):
            validated = None
            exp = None
            try:
                validated = model(**data)
            except ValidationError as ex:
                if isinstance(ex.payload, dict):
                    errors = {}
                    for field, error in ex.payload.items():
                        errors[field] = []
                        for er in error:
                            e = {"value": str(er["value"]), "error": er["error"]}
                            errors[field].append(e)
                else:
                    errors = "Missing Data."
                args = {
                    "errors": errors,
                    "error": f"Validation Error on model {model!s}",
                    "exception": f"{ex}",
                }
                exp = web.HTTPBadRequest(
                    reason=json_encoder(args), content_type="application/json"
                )
            except TypeError as ex:
                # print('TYPE ', ex)
                data = {
                    "error": f"Invalid type for {model!s}: {ex}",
                    "exception": f"{ex}",
                }
                exp = web.HTTPNotAcceptable(
                    reason=json_encoder(data), headers=headers, **args
                )
            except (ValueError, AttributeError) as ex:
                data = {
                    "error": f"Invalid Value for {model!s}: {ex}",
                    "exception": f"{ex}",
                }
                exp = web.HTTPNotAcceptable(
                    reason=json_encoder(data), content_type="application/json"
                )
            if exp is not None:
                if strict is True:
                    return exp  # exception
                else:
                    return validated
            else:
                return validated


class BaseView(web.View, BaseHandler, AbstractView):
    def __init__(self, request, *args, **kwargs):
        AbstractView.__init__(self, request)
        BaseHandler.__init__(self, *args, **kwargs)
        # CorsViewMixin.__init__(self)
        self._request = request
        self._connection: Callable = None

    async def get_connection(self):
        return self._connection

    async def connect(self, request):
        try:
            self._connection = await request.app["database"].acquire()
        except KeyError as e:
            raise InvalidArgument(
                "Cannot Access a DB connection in *database* App key. \
                Hint: enable a database connection on App using *enable_pgpool* attribute."
            ) from e
        except Exception as err:
            self.logger.exception(err, stack_info=True)
            raise NavException(f"Unable to access to Database: {err}") from err

    connection = connect

    async def close(self):
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def post_data(self) -> dict:
        params = {}
        if self.request.headers.get("Content-Type") == "application/json":
            try:
                return await self.get_json(self.request)
            except JSONDecodeError as ex:
                logging.exception(f"Empty or Wrong POST Data, {ex}")
                return None
        try:
            params = await self.request.post()
            if not params or len(params) == 0:
                if self.request.body_exists:
                    body = await self.request.read()
                    body = body.decode("ascii")
                    if body:
                        try:
                            params = dict(
                                (k, v if len(v) > 1 else v[0])
                                for k, v in parse.parse_qs(body).items()
                            )
                        except (KeyError, ValueError):
                            pass
        finally:
            return params  # pylint: disable=W0150


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
        except (ProviderError, DriverError) as ex:
            raise Exception(f"Error connecting to DB: {ex}") from ex
        except Exception as err:
            raise Exception(f"Error connecting to DB: {err}") from err

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
            except (ProviderError, DriverError) as err:
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
            except (ProviderError, DriverError) as ex:
                self._lasterr = ex
            except Exception as err:
                self._lasterr = err
                raise Exception(f"Error connecting to DB: {err}") from err
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
            except (ProviderError, DriverError) as ex:
                self._lasterr = ex
            except Exception as err:
                self._lasterr = err
                raise Exception(f"Error connecting to DB: {err}") from err
            finally:
                return result  # pylint: disable=W0150


async def load_models(app: str, model, tablelist: list):
    pool = app["database"]
    async with await pool.acquire() as conn:
        name = app["name"]
        if isinstance(tablelist, list):
            for table in tablelist:
                try:
                    query = await Model.makeModel(name=table, schema=name, db=conn)
                    model[table] = query
                except Exception as err:  # pylint: disable=W0703
                    logging.error(f"Error loading Model {table}: {err!s}")
            return model


class ModelView(BaseView):
    """ModelView.

    description: API View using AsyncDB Models.
    tags:
      - Model
      - AsyncDB Model
    parameters:
      - name: model
        in: Model
        type: Model
        required: true
        description: DB Model using asyncdb Model.
    """

    model: Model = None

    def __init__(self, request, *args, **kwargs):
        # self.model: Model = None
        self.models: dict = {}
        super(ModelView, self).__init__(request, *args, **kwargs)
        # getting model associated
        try:
            self.model = self.get_schema()
        except NoDataFound as err:
            raise NavException(
                f"Error on Getting Model {self.model}: {err}"
            ) from err

    def get_schema(self):
        if self.model:
            return self.model
        else:
            # TODO: try to discover from Model Name and model declaration
            # using importlib (from apps.{program}.models import Model)
            try:
                table = self.Meta.tablename
            except Exception as err:  # pylint: disable=W0703
                print(err)
                table = type(self).__name__
                self.Meta.tablename = table
            try:
                return self.models[table]
            except KeyError as err:
                # Model doesn't exists
                raise NoDataFound(
                    f"Model {table} Doesn't Exists"
                ) from err

    async def get_connection(self, driver: str = "database"):
        try:
            if not self.model.Meta.connection:
                self._connection = self.request.app[driver].acquire()
                self.model.Meta.connection = self._connection
        except Exception as err:
            raise NavException(
                f"ModelView Error: Cannot get Connection: {err}"
            ) from err

    async def get_data(self, params, args):
        db = self.request.app["database"]
        data = None
        async with await db.acquire() as conn:
            self.model.Meta.connection = conn
            try:
                if len(params) > 0:
                    print("FILTER")
                    query = await self.model.filter(**params)
                elif len(args) > 0:
                    print("GET")
                    query = await self.model.get(**args)
                    return query.dict()
                else:
                    print("ALL")
                    query = await self.model.all()
                if query:
                    data = [row.dict() for row in query]
                else:
                    raise NoDataFound('No Data was found')
            except NoDataFound:
                raise
            except Exception as err:
                raise NavException(
                    f"Error getting data from Model: {err}"
                ) from err
        await db.release(conn)
        return data



    def model_response(self, response, headers: dict = None):
        # TODO: check if response is empty
        if not response:
            return self.no_content(headers=headers)
        # return data only
        return self.json_response(response, headers=headers)

    def get_args(self, request: web.Request = None) -> dict:
        params = {}
        if not request:
            rq = self.request
        else:
            rq = request
        for arg in rq.match_info:
            try:
                val = rq.match_info.get(arg)
                object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        return params

    async def get_parameters(self):
        """Get Parameters.

        Get all parameters from URL or from query string.
        """
        args = self.get_args()
        params = self.query_parameters(self.request)
        return [args, params]

    async def get(self):
        args, params = await self.get_parameters()
        # TODO: check if QueryParameters are in list of columns in Model
        try:
            data = await self.get_data(params, args)
            return self.model_response(data)
        except NoDataFound:
            headers = {
                "X-STATUS": "EMPTY",
                "X-MESSAGE": f"Data on {self.Meta.tablename} not Found",
            }
            return self.no_content(headers=headers)
        except (ProviderError, DriverError) as err:
            return self.critical(request=self.request, exception=err, stacktrace="")

    async def patch(self):
        """
        patch.
            summary: return the metadata from table or, if we got post
            realizes a partially atomic updated of the query.
        """
        args, _ = await self.get_parameters()
        # try to got post data
        post = await self.json_data()
        if post:
            db = self.request.app["database"]
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                # trying to update the model
                update = await self.model.update(args, **post)
                if update:
                    data = update[0].dict()
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Resource not found: {post}",
                        request=self.request,
                        state=404,
                    )
        else:
            try:
                # getting metadata of Model
                qry = self.model(**args)
                data = {}
                for _, field in qry.columns().items():
                    key = field.name
                    _type = field.db_type()
                    default = None
                    if field.default is not None:
                        default = f"{field.default!r}"
                    data[key] = {"type": _type, "default": default}
                return self.model_response(data)
            except Exception as err:  # pylint: disable=W0703
                stack = traceback.format_exc()
                return self.critical(
                    request=self.request, exception=err, stacktrace=stack
                )

    async def post(self):
        """
        post.
            summary: update (or create) a row in table
        """
        args, _ = await self.get_parameters()
        post = await self.json_data()
        if not post:
            return self.error(
                request=self.request,
                response="Cannot Update row without JSON Data",
                state=406,
            )
        db = self.request.app["database"]
        # updating several at the same time:
        if isinstance(post, list):
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                # mass-update using arguments:
                try:
                    result = self.model.update(args, **post)
                    data = [row.dict() for row in result]
                    return self.model_response(data)
                except Exception as err:  # pylint: disable=W0703
                    trace = traceback.format_exc()
                    return self.critical(
                        request=self.request, exception=err, stacktrace=trace
                    )
        if len(args) > 0:
            parameters = {**args, **post}
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                try:
                    # check if exists first:
                    query = await self.model.get(**args)
                    if not query:
                        # object doesnt exists, need to be created:
                        result = await self.model.create([parameters])
                        query = await self.model.get(**parameters)
                        data = query.dict()
                        return self.model_response(data)
                except Exception as err:  # pylint: disable=W0703
                    print(err)
                    return self.error(
                        response=f"Error Saving Data {err!s}"
                    )
        # I need to use post data only
        try:
            db = self.request.app["database"]
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                qry = self.model(**post)
                if qry.is_valid():
                    await qry.save()
                    query = await qry.fetch(**args)
                    data = query.dict()
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Invalid data for Schema {self.Meta.tablename}",
                    )
        except Exception as err:  # pylint: disable=W0703
            print(err)
            trace = traceback.format_exc()
            return self.critical(exception=err, stacktrace=trace)

    async def delete(self):
        """ "
        delete.
           summary: delete a table object
        """
        args, params = await self.get_parameters()
        db = self.request.app["database"]
        try:
            result = None
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                if len(args) > 0:
                    # need to delete one
                    result = await self.model.remove(args)
                elif len(params) > 0:
                    result = await self.model.remove(params)
        except Exception as err:  # pylint: disable=W0703
            return self.error(
                request=self.request,
                response="Error Deleting Object",
                exception=err,
                state=400,
            )
        if result is not None:
            msg = {"result": result}
            headers = {
                "X-STATUS": "OK",
                "X-MESSAGE": f"Table row was deleted: {self.model!r}",
                "X-TABLE": self.Meta.tablename,
            }
            return self.model_response(msg, headers=headers)
        else:
            headers = {
                "X-STATUS": "Error",
                "X-MESSAGE": f"Row in Table {self.Meta.tablename} not deleted",
            }
            return self.error(
                response=f"Row in Table {self.Meta.tablename} not deleted",
                headers=headers,
                state=404,
            )

    async def put(self):
        """ "
        put.
           summary: insert a row in table
        """
        _, params = await self.get_parameters()
        post = await self.json_data()
        if not post:
            return self.error(
                request=self.request,
                response="Cannot Insert a row without post data",
                state=406,
            )
        parameters = {**params, **post}
        db = self.request.app["database"]
        async with await db.connection() as conn:
            self.model.Meta.connection = conn
            try:
                qry = self.model(**parameters)
                if qry.is_valid():
                    # TODO: if insert fails in constraint, trigger POST (UPDATE)
                    result = await self.model.create([parameters])
                    if result:
                        data = [row.dict() for row in result]
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Invalid data for Schema {self.Meta.tablename}",
                    )
            except (ProviderError, DriverError) as err:
                stack = traceback.format_exc()
                return self.critical(exception=err, stacktrace=stack)
            except Exception as err:  # pylint: disable=W0703
                stack = traceback.format_exc()
                return self.critical(
                    exception=err, stacktrace=stack, state=501
                )

    class Meta:
        tablename: str = ""


class ModelHandler(BaseView):
    model: BaseModel = None
    name: str = "Model"
    pk: str = "id"

    async def session(self):
        session = None
        try:
            session = await get_session(self.request)
        except (ValueError, RuntimeError) as err:
            return self.critical(
                reason="Error Decoding Session", request=self.request, exception=err
            )
        return session

    async def head(self):
        """Getting Client information."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=403)
        ## calculating resource:
        response = self.model.schema(as_dict=True)
        columns = list(response["properties"].keys())
        size = len(str(response))
        headers = {
            "Content-Length": size,
            "X-Columns": f"{columns!r}",
            "X-Model": self.model.__name__,
            "X-Tablename": self.model.Meta.name,
        }
        return self.no_content(headers=headers)

    async def get(self):
        """Getting Client information."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=403)
        ## getting all clients:
        args = self.match_parameters(self.request)
        try:
            if args["meta"] == ":meta":
                # returning JSON schema of Model:
                response = self.model.schema(as_dict=True)
                return self.json_response(response)
        except KeyError:
            pass
        try:
            data = await self.json_data()
        except (TypeError, ValueError, NavException):
            data = None
        ## validate directly with model:
        db = self.request.app["database"]
        ## getting first the id from params or data:
        try:
            objid = data[self.pk]
        except (TypeError, KeyError):
            try:
                objid = args["id"]
            except KeyError:
                objid = None
        if objid:
            # get data for specific client:
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                error = {"error": f"{self.name} was not Found"}
                try:
                    args = {self.pk: objid}
                    result = await self.model.get(**args)
                except NoDataFound:
                    self.error(exception=error, status=403)
                if not result:
                    self.error(exception=error, status=403)
                return self.json_response(result)
        else:
            try:
                async with await db.acquire() as conn:
                    self.model.Meta.connection = conn
                    result = await self.model.all()
                    return self.json_response(result)
            except ValidationError as ex:
                error = {
                    "error": f"Unable to load {self.name} info from Database",
                    "payload": ex.payload,
                }
                return self.critical(reason=error, status=501)
            except TypeError as ex:
                error = {
                    "error": f"Invalid payload for {self.name}",
                    "payload": ex,
                }
                return self.error(exception=error, status=406)
            except (DriverError, ProviderError, RuntimeError):
                error = {
                    "error": "Database Error",
                    "payload": ex,
                }
                return self.critical(reason=error, status=500)

    async def put(self):
        """Creating Client information."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=403)
        ### get session Data:
        try:
            data = await self.json_data()
        except (TypeError, ValueError, NavException):
            self.error(reason=f"Invalid {self.name} Data", status=403)
        ## validate directly with model:
        try:
            resultset = self.model(**data)  # pylint: disable=E1102
            db = self.request.app["database"]
            async with await db.acquire() as conn:
                resultset.Meta.connection = conn
                result = await resultset.insert()
                return self.json_response(result, status=201)
        except ValidationError as ex:
            error = {
                "error": f"Unable to insert {self.name} info",
                "payload": ex.payload,
            }
            return self.error(reason=error, status=400)
        except (TypeError, AttributeError, ValueError) as ex:
            error = {
                "error": f"Invalid payload for {self.name}",
                "payload": ex,
            }
            return self.error(exception=error, status=406)

    async def patch(self):
        """Patch an existing Client or retrieve the column names."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=403)
        ### get session Data:
        params = self.match_parameters()
        try:
            if params["meta"] == ":meta":
                ## returning the columns on Model:
                fields = self.model.__fields__
                return self.json_response(fields)
        except KeyError:
            pass
        try:
            data = await self.json_data()
        except (TypeError, ValueError, NavException):
            self.error(reason=f"Invalid {self.name} Data", status=403)
        ## validate directly with model:
        ## getting first the id from params or data:
        try:
            objid = data[self.pk]
        except (TypeError, KeyError):
            try:
                objid = params["id"]
            except (TypeError, KeyError):
                self.error(reason=f"Invalid {self.name} Data", status=400)
        db = self.request.app["database"]
        if objid:
            ## getting client
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                try:
                    args = {self.pk: objid}
                    result = await self.model.get(**args)
                except NoDataFound:
                    headers = {"x-error": f"{self.name} was not Found"}
                    self.no_content(headers=headers)
                if not result:
                    headers = {"x-error": f"{self.name} was not Found"}
                    self.no_content(headers=headers)
                ## saved with new changes:
                for key, val in data.items():
                    if key in result.get_fields():
                        result.set(key, val)
                data = await result.update()
                return self.json_response(data, status=202)
        else:
            self.error(reason=f"Invalid {self.name} Data", status=400)

    async def post(self):
        """Create or Update a Client."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=400)
        ### get session Data:
        params = self.match_parameters()
        try:
            data = await self.json_data()
        except (TypeError, ValueError, NavException):
            self.error(reason=f"Invalid {self.name} Data", status=400)
        ## validate directly with model:
        ## getting first the id from params or data:
        try:
            objid = data[self.pk]
        except (TypeError, KeyError):
            try:
                objid = params["id"]
            except (TypeError, KeyError):
                self.error(reason=f"Invalid {self.name} Data", status=400)
        db = self.request.app["database"]
        if objid:
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                error = {"error": "Client was not Found"}
                try:
                    args = {self.pk: objid}
                    result = await self.model.get(**args)
                except NoDataFound:
                    self.error(exception=error, status=400)
                if not result:
                    self.error(exception=error, status=400)
                ## saved with new changes:
                for key, val in data.items():
                    if key in result.get_fields():
                        result.set(key, val)
                data = await result.update()
                return self.json_response(data, status=202)
        else:
            # create a new client based on data:
            try:
                resultset = self.model(**data)  # pylint: disable=E1102
                async with await db.acquire() as conn:
                    resultset.Meta.connection = conn
                    result = await resultset.insert()  # TODO: migrate to use save()
                    return self.json_response(result, status=201)
            except ValidationError as ex:
                error = {
                    "error": f"Unable to insert {self.name} info",
                    "payload": ex.payload,
                }
                return self.error(reason=error, status=400)
            except (TypeError, AttributeError, ValueError) as ex:
                error = {
                    "error": f"Invalid payload for {self.name}",
                    "payload": ex,
                }
                return self.error(exception=error, status=406)

    async def delete(self):
        """Delete a Client."""
        session = await self.session()
        if not session:
            self.error(reason="Unauthorized", status=403)
        ### get session Data:
        params = self.match_parameters()
        try:
            data = await self.json_data()
        except (TypeError, ValueError):
            self.error(reason=f"Invalid {self.name} Data", status=400)
        except Exception:  # pylint: disable=W0703
            data = None
        ## getting first the id from params or data:
        try:
            objid = data[self.pk]
        except (TypeError, KeyError):
            try:
                objid = params["id"]
            except (TypeError, KeyError):
                self.error(reason=f"Invalid {self.name} Data", status=400)
        db = self.request.app["database"]
        if objid:
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                args = {self.pk: objid}
                result = await self.model.get(**args)
                if not result:
                    self.error(reason="Client was Not Found", status=204)
                # Delete them this Client
                data = await result.delete()
                return self.json_response(data, status=202)
        else:
            self.error(reason=f"Cannot Delete an Empty {self.name}", status=204)
