import asyncio
from functools import wraps
from typing import Callable
from aiohttp import web
from navigator_session import get_session
from navigator.auth import get_userdata

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
        if request is None:
            raise ValueError(f'web.Request was not found in arguments. {fn!s}')
        app = request.app
        auth = app["auth"]
        for backend in auth.backends():
            if await backend.check_credentials(request):
                return await func(*args, **kwargs)
            else:
                continue
        raise web.HTTPUnauthorized(
            reason="Access Denied",
            headers={
                hdrs.CONTENT_TYPE: 'text/html; charset=utf-8',
                hdrs.CONNECTION: 'keep-alive',
            }
        )
        # router = app.router
        # return web.HTTPFound(router["login"].url_for())
    return _wrap

def has_permission(func, permission, context=None):
    """Check user permissions.
    Return Function if the identity is allowed the permission in the
    current context, else raise ``web.HTTPUnauthorized()``
    """
    @wraps(func)
    async def _wrap(*args, **kwargs):
        pass
    return _wrap

def restricted(func, restrictions):
    """Restrict the Handler to certain Groups/Restriction Classes.
    Return Function if the identity is allowed under current restrictions,
    else raise ``web.HTTPUnauthorized()``
    """
    @wraps(func)
    async def _wrap(*args, **kwargs):
        pass
    return _wrap

def login_required(func: Callable) -> Callable:
    func.__login_required__ = True
    return func
