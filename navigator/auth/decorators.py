import asyncio
from functools import wraps
from typing import Callable
from aiohttp import web
from navigator.auth.sessions import get_session


def auth_required(func: Callable) -> Callable:
    """Decorator to check if an user has been authenticated for this request.
    """
    @wraps(func)
    async def _wrap(*args, **kwargs):
        # handling functions and class methods
        handler = args[0]
        if isinstance(handler, web.Request):
            request = handler
        else:
            request = (args[-1].request if isinstance(args[-1], web.View)
                       else args[-1])
        app = request.app
        auth = app["auth"]
        for backend in auth.backends():
            if await backend.check_credentials(request):
                return await func(*args, **kwargs)
            else:
                continue
        raise web.HTTPUnauthorized()
        # router = app.router
        # return web.HTTPFound(router["login"].url_for())
    return _wrap

def permission(self, identity, permission, context=None):
    """Check user permissions.
    Return Function if the identity is allowed the permission in the
    current context, else raise ``web.HTTPUnauthorized()``
    """
    @wraps(func)
    async def _wrap(*args, **kwargs):
    return _wrap

def login_required(func: Callable) -> Callable:
    func.__login_required__ = True
    return func
