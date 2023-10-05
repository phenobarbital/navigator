import asyncio
import datetime
from typing import Any, Optional, Union
from collections.abc import Callable
from dataclasses import dataclass
from urllib import parse
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
from datamodel.exceptions import ValidationError
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

    async def session(self):
        session = None
        try:
            session = await get_session(self.request)
        except (ValueError, RuntimeError) as err:
            return self.critical(
                reason="Error Decoding Session", request=self.request, exception=err
            )
        return session

    async def get_userid(self, session, idx: str = 'user_id') -> int:
        if not session:
            self.error(
                reason="Unauthorized",
                status=403
            )
        try:
            if 'session' in session:
                return session['session'][idx]
            else:
                return session[idx]
        except KeyError:
            self.error(reason="Unauthorized", status=403)

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
            self.logger.warning(
                "Passing *cls* attribute is deprecated for json_response."
            )
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
            self.logger.warning(
                f"Invalid JSON data: {err}"
            )
            return None

    async def body(self, request: web.Request = None) -> str:
        body = None
        if not request:
            request = self.request
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
            self.logger.debug(f"Invalid POST DATA: {err!s}")
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
