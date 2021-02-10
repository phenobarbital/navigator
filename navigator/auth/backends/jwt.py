"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import jwt
from aiohttp import web
from .base import BaseAuthHandler
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM
)

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = JWT_ALGORITHM
JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)


class JWTAuth(BaseAuthHandler):
    """Basic JWT Authentication."""
    user_attribute: str = 'user'
    pwd_atrribute: str = 'password'
    _scheme: str = 'Bearer'

    async def validate_session(self, login: str = None, password: str = None):
        # TODO: build validation logic
        if login == "phenobarbital":
            return True
        return False

    async def get_payload(self, request):
        ctype = request.content_type
        if request.method == 'GET':
            try:
                user = request.query.get(self.user_attribute, None)
                password = request.query.get(self.pwd_atrribute, None)
                return [user, password]
            except Exception:
                return None
        elif ctype in ('multipart/mixed', 'application/x-www-form-urlencoded'):
            data = await request.post()
            if len(data) > 0:
                user = post.get(self.user_attribute, None)
                password = post.get(self.pwd_atrribute, None)
                return [user, password]
            else:
                return None
        elif ctype == 'application/json':
            try:
                data = await request.json()
                user = data[self.user_attribute]
                password = data[self.pwd_atrribute]
                return [user, password]
            except Exception:
                return None
        else:
            return None

    async def check_credentials(self, request):
        try:
            user, pwd = await self.get_payload(request)
        except Exception:
            return False
        if not pwd and not user:
            return False
        else:
            # making validation
            if await self.validate_session(login=user, password=pwd):
                try:
                    payload = {
                        self.user_property: user,
                        'user_id': user,
                        'exp': datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
                    }
                    # TODO: functionality for Audience and Issuer
                    jwt_token = jwt.encode(
                        payload,
                        JWT_SECRET,
                        JWT_ALGORITHM
                    )
                    return {'token': jwt_token}
                except Exception as err:
                    print(err)
                    return False
            else:
                return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return await authz
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
