"""
RNC Token Authorization Middleware.
This token use a RNC algorithm to create a token-based authorization
for Navigator.
"""
from aiohttp import web
from typing import (
    Optional,
    Coroutine,
    Tuple
)
from navigator.libs.cypher import Cipher
from navigator.conf import (
    PARTNER_KEY,
    CYPHER_TYPE,
    PARTNER_SESSION_TIMEOUT
)
from .abstract import base_middleware

# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)


class troctoken_middleware(base_middleware):
    def __init__(
        self,
        user_fn: Optional[Coroutine] = None,
        protected_routes: Optional[Tuple] = tuple()
    ):
        """
        Check if an Auth Token was provided and returns based on
        an user Callback Function.

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

    async def middleware(self, app, handler):
        @web.middleware
        async def middleware(request):
            if await self.valid_routes(request):
                return await handler(request)
            try:
                token, scheme = self.get_authorization_header(request)
            except Exception as err:
                print(err)
                token = None
            if self.path_protected(request): # is a protected site.
                if not token:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Token',
                    )
                try:
                    payload = CIPHER.decode(
                        passphrase=token
                    )
                    if not payload:
                        raise web.HTTPForbidden(
                            reason="Invalid authorization Token"
                        )
                except ValueError as err:
                    raise web.HTTPUnauthorized(
                        reason="Token Decryption Error"
                    )
                except Exception as err:
                    raise web.HTTPBadRequest(
                        reason=f"Token Decryption Error: {err}"
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
                        reason=f'Exception on Callable called by {__name__!s} {err!s}'
                    )
            return await handler(request)
        return middleware
