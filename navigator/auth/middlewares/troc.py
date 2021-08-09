"""TROC Token Middleware.

Use RNC algorithm to create a token-based authentication/authorization
for Navigator.

Middleware Authorization.
"""
import sys
import json
from aiohttp import web
from navigator.libs.cypher import *

from navigator.conf import PARTNER_KEY, CYPHER_TYPE, PARTNER_SESSION_TIMEOUT

# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)


async def troctoken_middleware(app, handler):
    async def middleware(request):
        request.user = None
        try:
            troctoken = request.query.get("auth", request.headers.get("X-Token", None))
        except KeyError as err:
            troctoken = None
        if troctoken:
            try:
                payload = CIPHER.decode(passphrase=troctoken)
            except ValueError as err:
                print(err)
                raise web.HTTPUnauthorized(reason="Decryption authorization Error")
            except Exception as err:
                print(err)
                return web.json_response(
                    {"message": f"Token Error {err!s}"}, status=500
                )
            if not payload:
                raise web.HTTPForbidden(reason="Invalid authorization Token")
            # TODO: make the validation of the token
        return await handler(request)

    return middleware
