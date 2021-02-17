"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import jwt
from aiohttp import web
from .base import BaseAuthBackend
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM
)
import hashlib
import secrets

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = JWT_ALGORITHM
JWT_EXP_DELTA_SECONDS = int(SESSION_TIMEOUT)

# credentials algorithm
PWD_ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 150000
PWD_DIGEST = 'sha256'
KEY_LENGTH = 64

# "%s$%d$%s$%s" % (algorithm, iterations, salt, hash)

class BasicAuth(BaseAuthBackend):
    """Basic User/pasword with JWT Authentication."""
    user_attribute: str = 'user'
    pwd_atrribute: str = 'password'
    _scheme: str = 'Bearer'

    async def validate_session(self, login: str = None, password: str = None):
        # TODO: build validation logic
        if login == "phenobarbital":
            return True
        return False

    def set_password(
            self,
            password,
            token_num: int = 8,
            iterations: int = 150000,
            salt: str = None
    ):
        if not salt:
            salt = secrets.token_hex(token_num)
        key = hashlib.pbkdf2_hmac(
            PWD_DIGEST,
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations,
            dklen=KEY_LENGTH
        )
        hash = base64.b64encode(key).decode('ascii').strip()
        return f'{PWD_ALGORITHM}${iterations}${salt}${hash}'

    def check_password(self, current_password, password):
        algorithm, iterations, salt, hash = password.split('$', 3)
        assert algorithm == PWD_ALGORITHM
        iterations = int(iterations)
        compare_hash = self.set_password(
            password,
            iterations=iterations,
            salt=salt
        )
        return secrets.compare_digest(current_password, compare_hash)


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
                        'user_id': user
                    }
                    token = self.create_jwt(data=payload)
                    return {'token': token}
                except Exception as err:
                    print(err)
                    return False
            else:
                return False

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        pass

    async def get_session(self, request):
        """ Get user data from session."""
        pass

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
