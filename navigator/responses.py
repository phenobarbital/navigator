"""
Various kinds of Application Responses.

TODO: add FileResponse or JSONResponse or SSEResponse (server-side).
"""
from typing import (
    Any,
    Optional
)
from aiohttp import web
from aiohttp.web_exceptions import (
    HTTPNoContent,
)
from aiohttp_sse import sse_response, EventSourceResponse
from navigator.libs.json import json_encoder


__all__ = ('sse_response', 'EventSourceResponse', )


def Response(
    content: Any = None,
    text: Optional[str] = "",
    body: Any = None,
    status: int = 200,
    headers: dict = None,
    content_type: str = "text/plain",
    charset: Optional[str] = "utf-8",
    ) -> web.Response:
    """
    Response.
    Web Response Definition for Navigator
    """
    response = {
        "content_type": content_type,
        "charset": charset,
        "status": status
    }
    if headers:
        response["headers"] = headers
    if isinstance(content, str) or text is not None:
        response["text"] = content if content else text
    else:
        response["body"] = content if content else body
    return web.Response(**response)


def NoContent(headers: dict = None, content_type: str = "application/json") -> web.Response:
    response = {
        "content_type": content_type,
    }
    if headers:
        response["headers"] = headers
    response = HTTPNoContent(content_type=content_type)
    response.headers["Pragma"] = "no-cache"
    return response


def HTMLResponse(
    content: Any = None,
    text: Optional[str] = "",
    body: Any = None,
    status: int = 200,
    headers: dict = None,
    ) -> web.Response:
    """
    Sending response in HTML.
    """
    response = {
        "content": content,
        "text": text,
        "body": body,
        "headers": headers,
        "content_type": 'text/html',
        "status": status
    }
    return Response(**response)


def JSONResponse(
        content: Any,
        status: int = 200,
        headers: Optional[dict] = None,
        reason: Optional[str] = None,
        content_type: str = "application/json"
    ) -> web.Response:
    """
    JSONResponse.
     Sending responses using JSON.
    """
    response = {
        "content_type": content_type,
        "status": status,
        "dumps": json_encoder,
        "reason": reason
    }
    if headers:
        response["headers"] = headers

    return web.json_response(content, **response)
