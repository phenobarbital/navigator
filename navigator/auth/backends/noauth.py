"""Django Session Backend.

Navigator Authentication using Anonymous Backend
"""
import logging
import asyncio
from aiohttp import web, hdrs
from platformdirs import user_cache_dir
from .base import BaseAuthBackend
import uuid
from navigator.conf import (
    CREDENTIALS_REQUIRED,
    AUTH_SESSION_OBJECT,
    SECRET_KEY
)
from navigator.auth.sessions import get_session, new_session
from navigator.exceptions import (
    NavException,
    FailedAuth,
    InvalidAuth,
    AuthExpired
)

# Authenticated Entity
from navigator.auth.identities import AuthUser, Guest

class AnonymousUser(AuthUser):
    first_name: str = 'Anonymous'
    last_name: str = 'User'


class NoAuth(BaseAuthBackend):
    """Basic Handler for No authentication."""

    user_attribute: str = "userid"

    def __init__(
        self,
        user_attribute: str = "userid",
        userid_attribute: str = "userid",
        password_attribute: str = "password",
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        super(NoAuth, self).__init__(
            user_attribute,
            userid_attribute,
            password_attribute,
            credentials_required,
            authorization_backends,
            **kwargs
        )

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    def get_userdata(self):
        key = uuid.uuid4().hex
        userdata = {
            AUTH_SESSION_OBJECT: {
                "session": key,
                self.user_property: key,
                self.username_attribute: "Anonymous",
                "first_name": "Anonymous",
                "last_name": "User"
            }
        }
        return [ userdata, key ]

    async def authenticate(self, request):
        userdata, key = self.get_userdata()
        user = AnonymousUser(data=userdata[AUTH_SESSION_OBJECT])
        user.id = key
        user.add_group(Guest)
        user.set(self.username_attribute, 'Anonymous')
        logging.debug(f'User Created > {user}')
        payload = {
            self.session_key_property: key,
            self.user_property: None,
            self.username_attribute: "Anonymous",
            **userdata
        }
        token = self.create_jwt(data=payload)
        user.access_token = token
        await self.remember(
            request, key, userdata, user
        )
        return {
            "token": token,
            self.session_key_property: key,
            self.username_attribute: "Anonymous",
            **userdata
        }

    async def auth_middleware(self, app, handler):
        """
         NoAuth Middleware.
         Description: Basic Authentication for NoAuth, Basic, Token and Django.
        """
        async def middleware(request):
            logging.debug(f'MIDDLEWARE: {self.__class__.__name__}')
            jwt_token = None
            try:
                authz = await self.authorization_backends(app, handler, request)
                if authz:
                    # Authorization Exception
                    return await authz
            except Exception as err:
                logging.exception(
                    f'Error Processing Authorization Middlewares {err!s}'
                )
            try:
                auth = request.get('authenticated', False)
                if auth is True:
                    # already authenticated
                    return await handler(request)
            except KeyError:
                pass
            try:
                tenant, payload = self.decode_token(request)
                if payload:
                    # load session information
                    session = await get_session(request, payload, new = False)
                    try:
                        request.user = session.decode('user')
                        print('USER> ', request.user, type(request.user))
                        request.user.is_authenticated = True
                        request['authenticated'] = True
                    except Exception:
                        logging.error(
                            'Missing User Object from Session'
                        )
            except (AuthExpired, FailedAuth) as err:
                logging.error('Auth Middleware: Auth Credentials were expired')
                if CREDENTIALS_REQUIRED is True:
                    raise web.HTTPForbidden(
                        reason=err
                    )
            except NavException as err:
                logging.error('Auth Middleware: Invalid Signature or secret')
                if CREDENTIALS_REQUIRED is True:
                    raise web.HTTPClientError(
                        reason=err.message,
                        state=err.state
                    )
            except Exception as err:
                logging.error(f"Bad Request: {err!s}")
                if CREDENTIALS_REQUIRED is True:
                    raise web.HTTPClientError(
                        reason=err.message,
                        state=err.state
                    )
            return await handler(request)

        return middleware
