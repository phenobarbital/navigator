from typing import (
    Optional,
    Tuple
)
from collections.abc import Coroutine
import jwt
from aiohttp import web
from navconfig import config
from navigator_session import (
    SESSION_USER_PROPERTY
)
from navigator.conf import (
    SECRET_KEY,
    CREDENTIALS_REQUIRED
)
from .abstract import base_middleware


class jwt_middleware(base_middleware):
    def __init__(
        self,
        user_fn: Coroutine,
        user_property: str = SESSION_USER_PROPERTY,
        exclude_routes: Optional[Tuple] = tuple(),
        jwt_algorithm: str = 'HS256'
    ):
        """
        Simple Middleware to decrypt JWT tokens and return the payload to a
        Callable.

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
            RuntimeError: if middleware fails.
        """
        if not callable(user_fn):
            raise RuntimeError(
                f"User Function {user_fn!s} need to be an Asyncio Coroutine."
            )
            # TODO: adds a generic list of exclude routes
        self._fn = user_fn
        self.jwt_algorithm = jwt_algorithm

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
                token, _ = self.get_authorization_header(request, scheme = 'Bearer')
            except KeyError:
                token = None
            if CREDENTIALS_REQUIRED is True:
                if not token:
                    raise web.HTTPForbidden(
                        reason='Token Auth: Invalid authorization Token',
                    )
                try:
                    # process token:
                    payload = jwt.decode(
                        token,
                        SECRET_KEY,
                        algorithms=[self.jwt_algorithm]
                    )
                    if not payload:
                        raise web.HTTPForbidden(
                            reason="Invalid authorization Token"
                        )
                except (jwt.DecodeError) as err:
                    raise web.HTTPBadRequest(
                        reason=f"JWT: Invalid Token: {err}"
                    )
                except jwt.ExpiredSignatureError as err:
                    raise web.HTTPBadRequest(
                        reason=f"JWT: Expired Token or bad signature: {err}"
                    )
                except Exception as err:
                    raise web.HTTPBadRequest(
                        reason=f"JWT Token Decryption Error: {err}"
                    )
                try:
                    user = await self._fn(payload, request)
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
# async def jwt_middleware(app, handler):
#     async def middleware(request):
#         request.user = None
#         jwt_token = request.headers.get("Authorization", None)
#         if jwt_token:
#             try:
#                 payload = jwt.decode(
#                     jwt_token,
#                     SECRET_KEY,
#                     algorithms=[JWT_ALGORITHM]
#                 )
#                 print(payload)
#                 request.user = payload
#             except (jwt.DecodeError, jwt.ExpiredSignatureError) as err:
#                 print(err)
#                 return web.json_response({"message": "Invalid Token"}, status=400)
#         return await handler(request)

#     return middleware
