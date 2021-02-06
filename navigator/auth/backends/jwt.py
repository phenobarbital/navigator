"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import jwt
from aiohttp import web
from .base import BaseAuthHandler
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY
)

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = 'HS256'
JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)


class JWTAuth(BaseAuthHandler):
    """Basic JWT Authentication."""

    async def validate_user(self, login: str = None, password: str = None):
        if login == "phenobarbital":
            return True
        return False

    async def get_payload(self, request):
        ctype = request.content_type
        if request.method == 'GET':
            try:
                user = request.query.get('user', None)
                password = request.query.get('password', None)
                return [user, password]
            except Exception:
                return None
        elif ctype in ('multipart/mixed', 'application/x-www-form-urlencoded'):
            data = await request.post()
            if len(data) > 0:
                user = post.get('user', None)
                password = post.get('password', None)
                return [user, password]
            else:
                return None
        elif ctype == 'application/json':
            try:
                data = await request.json()
                user = data['user']
                password = data['password']
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
            if await self.validate_user(login=user, password=pwd):
                try:
                    payload = {
                        'user_id': user,
                        'exp': datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
                    }
                    jwt_token = jwt.encode(payload, JWT_SECRET, JWT_ALGORITHM)
                    return {'token': jwt_token}
                except Exception as err:
                    print(err)
                    return False
            else:
                return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            jwt_token = request.headers.get('Authorization', None)
            if jwt_token:
                try:
                    payload = jwt.decode(
                        jwt_token,
                        JWT_SECRET,
                        algorithms=[JWT_ALGORITHM]
                    )
                    print(payload)
                except (jwt.DecodeError) as err:
                    print(err)
                    return web.json_response(
                        {'message': 'Invalid Token'}, status=400
                    )
                except (jwt.ExpiredSignatureError) as err:
                    print(err)
                    return web.json_response(
                        {'message': str(err)}, status=403
                    )
            return await handler(request)
        return middleware
