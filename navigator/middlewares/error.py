"""Error Middleware.
"""
import asyncio
import traceback
from collections.abc import Awaitable, Callable
from aiohttp import web
from navconfig.conf import DEBUG
from navconfig.logging import logging
from navigator.responses import HTMLResponse, JSONResponse


error_codes = (400, 404, 500, 501, 502, 503)


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

def manage_exception(app: web.Application, response: web.Response = None, ex: BaseException = None, status: int = None) -> web.Response:
    if 'template' in app:
        use_template = True
    name = app['name']
    if response:
        status = response.status
        message = response.message
        ct = response.content_type
    else:
        message = None
        ct = 'text/html'
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
        "error": error,
        "message": detail,
        "stacktrace": stacktrace
    }
    if ct == 'application/json':
        return JSONResponse(payload, status=status)
    else:
        if use_template is True:
            pass
        else:
            data = error_page.format(**payload)
            print(data)
            return HTMLResponse(content=data, status=status)


async def error_middleware(
    app: web.Application,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    @web.middleware
    async def middleware_error(request: web.Request):
        try:
            response = await handler(request)
            if response.status in error_codes:
                if DEBUG is True:
                    return manage_exception(app, response=response)
                else:
                    return response
        except web.HTTPException as ex:
            if ex.status in error_codes:
                if DEBUG is True:
                    return manage_exception(app, status=ex.status, ex=ex)
                else:
                    raise
            else:
                raise
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            logging.warning(f'Request {request} has failed with exception: {ex!r}')
            if DEBUG is True:
                    return manage_exception(app, status=ex.status, ex=ex)
            else:
                raise
        return await handler(request)
    return middleware_error
