"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import jwt
from aiohttp import web
from .base import BaseAuthBackend
from datetime import datetime, timedelta
from aiohttp_session import get_session, new_session
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY
)
import hashlib
import base64
import secrets

# credentials algorithm
PWD_ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 150000
PWD_DIGEST = 'sha256'
KEY_LENGTH = 64

# "%s$%d$%s$%s" % (algorithm, iterations, salt, hash)

class BasicAuth(BaseAuthBackend):
    """Basic User/pasword with JWT Authentication."""
    user_attribute: str = 'user'
    username_attribute: str = 'username'
    pwd_atrribute: str = 'password'
    scheme: str = 'Basic'

    async def validate_user(self, login: str = None, password: str = None):
        # get the user based on Model
        search = {
            self.username_attribute: login
        }
        try:
            user = await self.get_user(**search)
        except UserDoesntExists as err:
            raise UserDoesntExists(f'User {login} doesnt exists')
        except Exception as err:
            raise Exception(err)
        try:
            # later, check the password
            pwd = user[self.pwd_atrribute]
            if self.check_password(pwd, password):
                # return the user Object
                return user
            else:
                raise InvalidAuth('Invalid Credentials')
        except Exception as err:
            raise Exception(err)
        return None

    def set_password(
            self,
            password,
            token_num: int = 6,
            iterations: int = 80000,
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
        algorithm, iterations, salt, hash = current_password.split('$', 3)
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
            raise NavException(err, state=400)
        if not pwd and not user:
            raise InvalidAuth('Invalid Credentials', state=401)
        else:
            # making validation
            try:
                user = await self.validate_user(login=user, password=pwd)
            except UserDoesntExists as err:
                raise UserDoesntExists(err)
            except InvalidAuth as err:
                raise InvalidAuth(err, state=401)
            except Exception as err:
                raise NavException(err, state=500)
            try:
                userdata = self.get_userdata(user)
                # Create the User session and returned.
                session = await self._session.create_session(
                    request,
                    user,
                    userdata
                )
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: user[self.username_attribute],
                    'user_id': user[self.userid_attribute]
                }
                token = self.create_jwt(data=payload)
                return {'token': token}
            except Exception as err:
                print(err)
                return False

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        pass

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return await authz
            try:
                jwt_token = self.decode_token(request)
            except NavException as err:
                print('Error HERE: ', err, err.state)
                response = {
                    "message": "Token Error",
                    "error": err.message,
                    "status": err.state
                }
                print(response)
                return web.json_response(response, status=err.state)
            except Exception as err:
                raise web.HTTPBadRequest(
                    body=f'Bad Request: {err!s}'
                )
            if self.credentials_required is True:
                raise web.HTTPUnauthorized(
                    body='Unauthorized'
                )
            return await handler(request)
        return middleware
