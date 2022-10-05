"""
Simply Token Authorization with Callback Support.
"""
from typing import (
    Optional
)
from collections.abc import Coroutine
from aiohttp import web
from navigator_session import (
    SESSION_USER_PROPERTY
)
from navigator.conf import (
    config,
    CREDENTIALS_REQUIRED
)
from .abstract import base_middleware

class token_middleware(base_middleware):
    def __init__(
        self,
        user_fn: Coroutine,
        user_property: str = SESSION_USER_PROPERTY,
        exclude_routes: Optional[tuple] = tuple()
    ):
        """
        Check if an Auth Token was provided and returns based on
        an user Callback Function.

        Args:
            user_fn: any User Callable Coroutine, to process the received token.
              TODO: if not, can we use own token factory.
            user_property: the User Object returned by callback is saved
              on this property under the request.
            exclude_routes: any path that needs to be excluded for Token Auth
        Returns:
            handler if User exists, HTTP Forbidden if callback returns false.
            HTTP Unauthorized if Token is missing (only if credential required is TRUE)
        Raises:
            RuntimeError: when callable is not a Coroutine.
        """
        if not callable(user_fn):
            raise RuntimeError(
                f"User Function {user_fn!s} need to be an Asyncio Coroutine."
            )
            # TODO: adds a generic list of exclude routes
        self._fn = user_fn

        if exclude_routes is None:
            self.exclude_routes = config.get('EXCLUDED_ROUTES', tuple())
        else:
            self.exclude_routes = exclude_routes
        # user property
        self.user_property = user_property

    async def middleware(self, app, handler):
        @web.middleware
        async def middleware(request):
            if await self.valid_routes(request):
                return await handler(request)
            try:
                token, scheme = self.get_authorization_header(request)
            except KeyError:
                token = None
            if CREDENTIALS_REQUIRED is True:
                if not token:
                    raise web.HTTPForbidden(
                        reason='Token Auth: Invalid authorization Token',
                    )
                try:
                    user = await self._fn(token, scheme, request)
                    if user:
                        request[self.user_property] = user
                        request.user = user
                        print(user)
                    else:
                        raise web.HTTPForbidden(
                            reason='Access Restricted'
                        )
                except Exception as err:
                    raise web.HTTPBadRequest(
                        reason=f'Token Auth: Exception on Callable Return {err!s}'
                    )
            return await handler(request)
        return middleware
