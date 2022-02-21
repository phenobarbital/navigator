import base64
import rapidjson
import logging
import time
from aiohttp import web
from typing import (
    Optional,
    Coroutine,
    Tuple
)
from navigator.conf import (
    SESSION_TIMEOUT,
    SESSION_KEY,
    SECRET_KEY,
    SESSION_PREFIX,
    CREDENTIALS_REQUIRED,
    SESSION_STORAGE,
    SESSION_USER_PROPERTY
)
from .abstract import base_middleware


class django_middleware(base_middleware):
    def __init__(
        self,
        user_fn: Optional[Coroutine] = None,
        protected_routes: Optional[Tuple] = tuple()
    ):
        """
        Extract an user Session from Django using a Middleware.

        The Optional Callback can receive the Payload of the deciphered token
        and the Request.
        """
        if user_fn is not None and not callable(user_fn):
            raise RuntimeError(
                f"If defined, User Function {user_fn!s} need to be Callable."
            )
        self._fn = user_fn
        if protected_routes:
            self.protected_routes = protected_routes

    def get_authorization_header(self, request: web.Request):
        sessionid = request.headers.get("x-sessionid", None)
        if not sessionid:
            raise web.HTTPBadRequest(
                reason=f'Django Middleware: use Header different from X-Sessionid is not available'
            )
        return sessionid

    async def middleware(self, app, handler):
        @web.middleware
        async def middleware(request):
            if await self.valid_routes(request):
                return await handler(request)
            try:
                sessionid = self.get_authorization_header(request)
            except Exception as err:
                sessionid = None
            if self.path_protected(request): # is a protected site.
                if not sessionid:
                    raise web.HTTPForbidden(
                        reason='Django Middleware: Invalid authorization Token',
                    )
                try:
                    redis = app["redis"]
                    payload = await redis.get(f"{SESSION_PREFIX}:{sessionid}")
                    if not payload:
                        raise web.HTTPBadRequest(
                            reason="Django Middleware: Invalid Django Session"
                        )
                    data = base64.b64decode(payload)
                    session_data = data.decode("utf-8").split(":", 1)
                    user = rapidjson.loads(session_data[1])
                    data = {
                        "key": sessionid,
                        "session_id": session_data[0],
                        **user
                    }
                    try:
                        user = await self._fn(data, request)
                        if user:
                            request[self.user_property] = user
                            request.user = user
                        else:
                            raise web.HTTPForbidden(
                                reason='Access Restricted'
                            )
                    except Exception as err:
                        raise web.HTTPBadRequest(
                            reason=f'Exception on Callable called by {__name__!s} {err!s}'
                        )
                except Exception as err:
                    raise web.HTTPBadRequest(
                        reason=f'Django Middleware: Error decoding: {err!s}'
                    )
            return await handler(request)
        return middleware
