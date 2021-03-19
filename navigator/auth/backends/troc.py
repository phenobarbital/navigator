"""TROC Backend.

Troc Authentication using RNC algorithm.
"""
import jwt
from aiohttp import web
import rapidjson
from .base import BaseAuthBackend
from navigator.libs.cypher import *
from datetime import datetime, timedelta
from aiohttp_session import get_session, new_session
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth
from navigator.conf import (
    PARTNER_KEY,
    CYPHER_TYPE,
    SESSION_TIMEOUT,
    SECRET_KEY
)
import hashlib
import base64
import secrets

# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)


class TrocAuth(BaseAuthBackend):
    """TROC authentication Header."""
    user_attribute: str = 'user'
    username_attribute: str = 'email'
    _scheme: str = 'Bearer'

    def __init__(
            self,
            user_property: str = 'user',
            user_attribute: str = 'user',
            userid_attribute: str = 'user_id',
            username_attribute: str = 'email',
            credentials_required: bool = False,
            authorization_backends: tuple = (),
            session_type: str = 'cookie',
            **kwargs
    ):
        super().__init__(
            user_property,
            user_attribute,
            userid_attribute,
            username_attribute,
            credentials_required,
            authorization_backends,
            session_type,
            **kwargs
        )
        # forcing to use Email as Username Attribute
        self.username_attribute = 'email'

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {
            self.username_attribute: login
        }
        try:
            user = await self.get_user(**search)
            return user
        except UserDoesntExists as err:
            raise UserDoesntExists(f'User {login} doesnt exists')
        except Exception as err:
            raise Exception(err)
        return None

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
        except Exception as err:
            raise NavException(err, state=400)
        if not troctoken:
            raise InvalidAuth('Invalid Credentials', state=401)
        else:
            # getting user information
            # TODO: making the validation of token and expiration
            try:
                data = rapidjson.loads(CIPHER.decode(passphrase=troctoken))
            except Exception as err:
                raise InvalidAuth(f'Invalid TROC Token: {err!s}', state=401)
            # making validation
            try:
                username = data[self.username_attribute]
            except KeyError as err:
                raise InvalidAuth(f'Missing Email attribute: {err!s}', state=401)
            try:
                user = await self.validate_user(
                    login=username
                )
            except UserDoesntExists as err:
                raise UserDoesntExists(err)
            except Exception as err:
                raise NavException(err, state=500)
            try:
                userdata = self.get_userdata(user)
                userdata['Payload'] = data
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
                response = {
                    "message": "TROC Token Error",
                    "error": err.message,
                    "status": err.state
                }
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
