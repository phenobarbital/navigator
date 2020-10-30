#!/usr/bin/env python3
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aiohttp import web
from aiohttp.web import middleware


def check_path(path):
    result = True
    for r in ["/login", "logout", "/static/", "/signin", "/signout", "/_debugtoolbar/"]:
        if path.startswith(r):
            result = False
    return result


@middleware
async def basic_middleware(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.Response]]
):
    resp = await handler(request)
    return resp
