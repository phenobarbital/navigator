"""Error Middleware.
"""
import asyncio
import traceback
from collections.abc import Awaitable, Callable
from aiohttp import web, hdrs
from aiohttp.web_urldispatcher import SystemRoute
from navconfig import DEBUG
from navconfig.logging import logging
from ..responses import HTMLResponse, JSONResponse


error_codes = (404, 500, 501, 502, 503, 0, -1)

not_found = """
<h1>{name}</h1>
<div id="main">
    <div>
        <h1>Error {status}</h1>
        <h3>{error}</h3>
        <h4>URL: {url}</h4>
    </div>
</div>
<div>
<p>{message}</p>
<h4>Stacktrace: </h4>
<div><pre>
{stacktrace}</pre>
</div>
</div>
"""


error_page = """
<h1>{name}</h1>
<div id="main">
    <div>
        <h1>Error {status}</h1>
        <h3>{error}</h3>
    </div>
</div>
<div>
<p>{message}</p>
<h4>Stacktrace: </h4>
<div><pre>
{stacktrace}</pre>
</div>
</div>
"""


def manage_notfound(
    app: web.Application,
    request: web.Request,
    response: web.Response = None,
    ex: BaseException = None,
    status: int = None,
) -> web.Response:
    name = app["name"]
    if response:
        message = response.reason
        status = response.status
        ct = response.content_type
    else:
        message = None
        ct = "text/html"
    if status is None:
        status = 404
    if ex is not None:
        error = ex.__class__.__name__
        detail = str(ex)
        stacktrace = traceback.format_exc(limit=20, chain=True)
    else:
        error = None
        detail = message
        stacktrace = None
    payload = {
        "name": name,
        "status": status,
        "url": request.rel_url,
        "error": error,
        "message": detail,
        "stacktrace": stacktrace,
    }
    if ct == "application/json":
        return JSONResponse(payload, status=status)
    else:
        data = not_found.format(**payload)
        return HTMLResponse(content=data, status=status)


def manage_exception(
    app: web.Application,
    response: web.Response = None,
    ex: BaseException = None,
    status: int = None,
) -> web.Response:
    message = None
    stacktrace = None
    error = "HTTP Error"
    ct = "text/html"
    if "template" in app:
        use_template = True
    else:
        use_template = False
    name = app["name"]
    if status == -1:
        ct = "text/html"
        status = 500
    elif status is None:
        status = 500
    if response is not None:
        if isinstance(response, web.HTTPException):
            error = response.__class__.__name__
            status = response.status
            ct = response.content_type
            message = str(response)
        elif isinstance(response, Exception):
            error = response.__class__.__name__
            message = str(response)
            status = 500
        elif isinstance(response, web.StreamResponse):
            error = response.__class__.__name__
            message = response.text
            status = response.status
        else:
            try:
                error = response.__class__.__name__
                message = response.message
                status = response.code
            except AttributeError:
                status = 500
                message = str(response)
    elif ex is not None:
        error = ex.__class__.__name__
        if isinstance(ex, web.HTTPException):
            ct = ex.content_type
            status = ex.status
            message = ex.text
        stacktrace = traceback.format_exc(limit=20, chain=False)
    else:
        message = None
        ct = "text/html"
    if ct == "application/json":
        payload = {
            "name": name,
            "status": status,
            "error": error,
            "message": message,
            "traceback": str(stacktrace),
        }
        return JSONResponse(payload, status=status)
    else:
        payload = {
            "name": name,
            "status": status,
            "error": error,
            "message": message,
            "stacktrace": stacktrace,
        }
        if use_template is True:
            data = error_page.format(**payload)
            return HTMLResponse(content=data, status=status)
        else:
            data = error_page.format(**payload)
            return HTMLResponse(content=data, status=status)


async def error_middleware(
    app: web.Application,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """
    Error Middleware.
    Description: Managing Errors on DEBUG Mode.
    """

    @web.middleware
    async def middleware_error(request: web.Request) -> web.StreamResponse:
        if isinstance(request.match_info.route, SystemRoute):  # eg. 404
            return await handler(request)

        if request.method == hdrs.METH_OPTIONS:
            return await handler(request)
        ### checking for Errors:
        try:
            response = await handler(request)
            if response is not None:
                if response.status in error_codes:
                    if DEBUG is True:
                        return manage_exception(app, response=response)
                    return response
            else:
                raise web.HTTPServerError(
                    reason="Error: Empty Response, maybe forgot making a *return* in your response?"
                )
        except web.HTTPException as ex:
            if ex.status == 404:
                if DEBUG is True:
                    return manage_notfound(
                        app, request=request, status=ex.status, ex=ex
                    )
            elif ex.status in error_codes:
                if DEBUG is True:
                    return manage_exception(app, response=None, ex=ex, status=ex.status)
                else:
                    raise
            else:
                raise
        except asyncio.CancelledError:
            pass
        except Exception as ex:  # pylint: disable=W0703
            logging.warning(f"Request {request} has failed with exception: {ex!r}")
            if DEBUG is True:
                return manage_exception(app, status=500, ex=ex)
            else:
                raise
        return response

    return middleware_error
