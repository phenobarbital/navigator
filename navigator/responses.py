"""
Various kinds of Application Responses.
"""
from typing import (
    Any,
    Optional
)
from aiohttp import web
from aiohttp_sse import sse_response, EventSourceResponse


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
