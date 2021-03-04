"""Django Session Backend.

Navigator Authentication using Django Session Backend
description: read the Django session from Redis Backend and decrypt.
"""
import base64
import rapidjson
import logging
import asyncio
import jwt
from aiohttp import web, hdrs
from asyncdb import AsyncDB
from .base import BaseAuthBackend
from navigator.exceptions import NavException, UserDoesntExists, InvalidAuth
from datetime import datetime, timedelta
from navigator.conf import (
    SESSION_URL,
    SESSION_TIMEOUT,
    SECRET_KEY,
    PARTNER_KEY,
    JWT_ALGORITHM,
    SESSION_PREFIX,
    default_dsn
)


class TokenAuth(BaseAuthBackend):
    """API Token Authentication Handler."""
    connection = None
    _scheme: str = 'Bearer'

    def configure(self, app, router):
        async def _make_connection():
            try:
                self.connection = AsyncDB('pg', dsn=default_dsn)
                await self.connection.connection()
            except Exception as err:
                print(err)
                raise Exception(err)
        asyncio.get_event_loop().run_until_complete(
            _make_connection()
        )
        # executing parent configurations
        super(TokenAuth, self).configure(app, router)

    async def get_payload(self, request):
        token = None
        tenant = None
        id = None
        try:
            if 'Authorization' in request.headers:
                try:
                    scheme, id = request.headers.get(
                        'Authorization'
                    ).strip().split(' ', 1)
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid authorization Header',
                    )
                if scheme != self._scheme:
                    raise web.HTTPForbidden(
                        reason='Invalid Authorization Scheme',
                    )
                try:
                    tenant, token = id.split(':')
                except ValueError:
                    raise web.HTTPForbidden(
                        reason='Invalid Token Structure',
                    )
        except Exception as e:
            print(e)
            return None
        return [tenant, token]

    async def validate_session(self, key: str = None):
        try:
            result = await self.redis.get("{}:{}".format(SESSION_PREFIX, key))
            if not result:
                return False
            data = base64.b64decode(result)
            session_data = data.decode("utf-8").split(":", 1)
            user = rapidjson.loads(session_data[1])
            session = {
                "key": key,
                "session_id": session_data[0],
                self.user_property: user
            }
            return session
        except Exception as err:
            print(err)
            logging.debug("Django Session Decoding Error: {}".format(err))
            return False

    async def reconnect(self):
        if not self.connection or not self.connection.is_connected():
            await self.connection.connection()

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {
            self.userid_attribute: login
        }
        try:
            user = await self.get_user(**search)
            return user
        except UserDoesntExists as err:
            raise UserDoesntExists(f'User {login} doesnt exists')
        except Exception as err:
            raise Exception(err)
        return None

    async def check_credentials(self, request):
        try:
            sessionid = await self.get_payload(request)
            logging.debug(f'Session ID: {sessionid}')
        except Exception:
            raise NavException(err, state=400)
        if not sessionid:
            raise InvalidAuth('Invalid Credentials', state=401)
        else:
            # getting user information
            # TODO: making the validation of token and expiration
            try:
                data = await self.validate_session(key=sessionid)
            except Exception as err:
                raise InvalidAuth(f'Invalid Session: {err!s}', state=401)
            # making validation
            try:
                u = data[self.user_property]
                username = u[self.userid_attribute]
            except KeyError as err:
                print(err)
                raise InvalidAuth(
                    f'Missing {self.userid_attribute} attribute: {err!s}',
                    state=401
                )
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
                userdata['session'] = data
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

    async def get_token_info(self, request, tenant, payload):
        try:
            name = payload['name']
            partner = payload['partner']
        except KeyError as err:
            return [False, False]
        sql = f"""
        SELECT grants FROM troc.api_keys
        WHERE name='{name}' AND partner='{partner}'
        AND enabled = TRUE AND revoked = FALSE AND '{tenant}'= ANY(programs)
        """
        try:
            result, error = await self.connection.queryrow(sql)
            if error or not result:
                return [False, False]
            else:
                grants = result['grants']
                return [partner, grants]
        except Exception as err:
            logging.exception(err)
            return [False, False]

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return await authz
            tenant, token = await self.get_payload(request)
            if token:
                try:
                    payload = jwt.decode(
                        token,
                        PARTNER_KEY,
                        algorithms=[JWT_ALGORITHM],
                        leeway=30
                    )
                    logging.debug(f'Decoded Token: {payload!s}')
                    partner, grants = await self.get_token_info(request, tenant, payload)
                    if not partner:
                        raise web.HTTPUnauthorized(
                            body='Not Authorized',
                        )
                    else:
                        session = await self._session.get_session(request)
                        session['grants'] = grants
                        session['partner'] = partner
                        session['tenant'] = tenant
                except (jwt.DecodeError) as err:
                    raise web.HTTPBadRequest(
                        reason=f'Token Decoding Error: {err!r}'
                    )
                except jwt.InvalidTokenError as err:
                    print(err)
                    raise web.HTTPBadRequest(
                        reason=f'Invalid authorization token {err!s}'
                    )
                except (jwt.ExpiredSignatureError) as err:
                    print(err)
                    raise web.HTTPBadRequest(
                        reason=f'Token Expired: {err!s}'
                    )
                except Exception as err:
                    print(err, err.__class__.__name__)
                    raise web.HTTPBadRequest(
                        reason=f'Bad Authorization Request: {err!s}'
                    )
            else:
                if self.credentials_required is True:
                    raise web.HTTPUnauthorized(
                        body='Missing Authorization Session',
                    )
            return await handler(request)
        return middleware
