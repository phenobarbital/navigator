"""
APIKEY infraestructure for NAVIGATOR.

Simple API Key/Secret Validator for Navigator using a Middleware.
"""
import logging
from aiohttp import web
from typing import (
    Optional,
    Coroutine,
    Tuple
)
from .abstract import base_middleware


class apikey_middleware(base_middleware):
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

    def get_authorization_header(
            self,
            request: web.Request,
            scheme: Optional[str] = None
        ):
        """
        Get the key and secret from header
        """
        token = None
        if 'x-api-key' in request.headers:
            try:
                token = request.headers['x-api-key'].strip()
            except KeyError:
                raise web.HTTPUnauthorized(
                    reason='API Key Auth: Missing authorization header',
                )
            except ValueError:
                raise web.HTTPForbidden(
                    reason='API Key Auth: Invalid authorization header',
            )
        else:
            try:
                token = request.query.get("api_key").strip()
            except KeyError as err:
                token = None
        return token

    async def middleware(self, app, handler):
        @web.middleware
        async def middleware(request):
            if await self.valid_routes(request):
                return await handler(request)
            try:
                key = self.get_authorization_header(request)
            except Exception as err:
                logging.exception(err)
                key = None
            if self.path_protected(request): # is a protected site.
                if not key:
                    raise web.HTTPForbidden(
                        reason='Missing API Key Authentication',
                    )
                try:
                    db = app['database']
                    async with await db.acquire() as conn:
                        payload = await conn.fetch_one(
                            "SELECT user_id, name from public.api_keys where token = $1 AND (expiration >= extract(epoch from now()) or expiration = 0)",
                            key
                        )
                    if not payload:
                        raise web.HTTPForbidden(
                            reason="Access is Restricted"
                        )
                except Exception as err:
                    raise web.HTTPBadRequest(
                        reason=f"API Key Decryption Error: {err}"
                    )
                try:
                    if self._fn:
                        user = await self._fn(payload, request)
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
            return await handler(request)
        return middleware
