import asyncio
from http import HTTPStatus
from typing import Callable

from aiohttp import web
from aiohttp_session import get_session


async def auth_middleware(app, handler: Callable) -> web.Response:
    async def middleware(request: web.Request):
        require_login = getattr(handler, "__login_required__", False)
        session = await get_session(request)
        request.user = None
        if require_login:
            if not "user_id" in session:
                raise web.HTTPSeeOther(location="/login")
        # requires authorization
        try:
            for backend in app["auth"].backends():
                result = await backend.check_authorization(request)
                if result:
                    request.user = result
                    break  # authorization was correct
        except Exception as err:
            return web.Response(text="Unauthorized", status=HTTPStatus.UNAUTHORIZED)
        return await handler(request)

    return middleware
