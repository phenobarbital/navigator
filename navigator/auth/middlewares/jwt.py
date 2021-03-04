import jwt
from aiohttp import web
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY
)

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = 'HS256'
JWT_EXP_DELTA_SECONDS = SESSION_TIMEOUT

async def jwt_middleware(app, handler):
    async def middleware(request):
        request.user = None
        jwt_token = request.headers.get('Authorization', None)
        print(jwt_token)
        if jwt_token:
            try:
                payload = jwt.decode(
                    jwt_token,
                    JWT_SECRET,
                    algorithms=[JWT_ALGORITHM]
                )
                print(payload)
            except (jwt.DecodeError, jwt.ExpiredSignatureError) as err:
                print(err)
                return web.json_response(
                    {'message': 'Invalid Token'}, status=400
                )
        return await handler(request)
    return middleware
