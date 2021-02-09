"""TROC Backend.

Troc Authentication using RNC algorithm.
"""
import jwt
from .base import BaseAuthHandler
from navigator.libs.cypher import *
from datetime import datetime, timedelta
from navigator.conf import (
    PARTNER_KEY,
    CYPHER_TYPE,
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM
)
JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = JWT_ALGORITHM
JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)

# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)

class TrocAuth(BaseAuthHandler):
    """TROC authentication Header."""
    _scheme: str = 'Bearer'

    async def get_payload(self, request):
        troctoken = None
        try:
            if 'Authorization' in request.headers:
                try:
                    scheme, troctoken = request.headers.get(
                        'Authorization'
                    ).strip().split(' ')
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Header',
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason='Invalid Session scheme',
                    )
            else:
                try:
                    troctoken = request.query.get('auth', None)
                except Exception as e:
                    print(e)
                    return None
        except Exception as e:
            print(e)
            return None
        return troctoken

    async def check_credentials(self, request):
        try:
            troctoken = await self.get_payload(request)
        except Exception:
            return False
        if not troctoken:
            return False
        else:
            try:
                # TODO: making the validation of token and expiration
                user = CIPHER.decode(passphrase=troctoken)
                payload = {
                    self.user_property: user,
                    'user_id': user,
                    'exp': datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
                }
                jwt_token = jwt.encode(
                    payload,
                    JWT_SECRET,
                    JWT_ALGORITHM
                )
                return {'token': jwt_token}
            except (ValueError):
                return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return authz
            jwt_token = None
            if 'Authorization' in request.headers:
                try:
                    scheme, jwt_token = request.headers.get(
                        'Authorization'
                    ).strip().split(' ')
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Header',
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason='Invalid Session scheme',
                    )
            if jwt_token:
                try:
                    payload = jwt.decode(
                        jwt_token,
                        JWT_SECRET,
                        algorithms=[JWT_ALGORITHM],
                        leeway=30
                    )
                    print(payload)
                except (jwt.DecodeError) as err:
                    print(err)
                    return web.json_response(
                        {'message': 'Invalid Token'}, status=400
                    )
                except jwt.InvalidTokenError as err:
                    print(err)
                    return web.json_response(
                        {'message': f'Invalid authorization token {err!s}'}, status=403
                    )
                except (jwt.ExpiredSignatureError) as err:
                    print(err)
                    return web.json_response(
                        {'message': f'Token Expired {err!s}'}, status=403
                    )
            else:
                if self.credentials_required is True:
                    raise web.HTTPUnauthorized(
                        reason='Unauthorized', status=403
                    )
            return await handler(request)
        return middleware
