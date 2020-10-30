import asyncio
from functools import wraps
from typing import Callable

from aiohttp import web
from aiohttp_session import get_session


def authorization_required(func: Callable) -> Callable:
    @wraps(func)
    async def _wrap(*args, **kwargs):
        # handling functions and class methods
        handler = args[0]
        if isinstance(handler, web.Request):
            request = handler
        else:
            request = args[1]
        app = request.app
        router = app.router
        auth = app["auth"]
        for backend in auth.backends():
            if await backend.check_authorization(request):
                return await func(*args, **kwargs)
            else:
                continue
        return web.HTTPFound(router["login"].url_for())

    return _wrap


def login_required(func: Callable) -> Callable:
    func.__login_required__ = True
    return func
