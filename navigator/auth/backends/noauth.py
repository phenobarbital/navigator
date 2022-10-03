"""Django Session Backend.

Navigator Authentication using Anonymous Backend
"""
import logging
import uuid
from aiohttp import web
from navigator_session import (
    get_session,
    AUTH_SESSION_OBJECT
)
from navigator.conf import (
    CREDENTIALS_REQUIRED
)
from navigator.exceptions import (
    NavException,
    FailedAuth,
    AuthExpired
)
# Authenticated Entity
from navigator.auth.identities import AuthUser, Guest
from .base import BaseAuthBackend

class AnonymousUser(AuthUser):
    first_name: str = 'Anonymous'
    last_name: str = 'User'


class NoAuth(BaseAuthBackend):
    """Basic Handler for No authentication."""
    userid_attribute: str = "userid"
    user_attribute: str = "userid"
    _ident: AuthUser = AnonymousUser

    def configure(self, app, router, handler):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    def get_userdata(self, user = None):
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
        user = await self.create_user(
            userdata[AUTH_SESSION_OBJECT]
        )
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
                if authz is not None:
                    # Authorization Exception
                    return await handler(request)
            except Exception as err:
                logging.exception(
                    f'Error Processing Base Authorization Backend: {err!s}'
                )
            try:
                if request.get('authenticated', False) is True:
                    # already authenticated
                    return await handler(request)
            except KeyError:
                pass
            try:
                _, payload = self.decode_token(request)
                if payload:
                    # load session information
                    session = await get_session(request, payload, new = False)
                    try:
                        try:
                            request.user = session.decode('user')
                            request.user.is_authenticated = True
                        except RuntimeError:
                            logging.error(
                                'NAV: Unable to decode User session from jsonpickle.'
                            )
                            # Error decoding user session, try to create them instead
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
                        reason=err.message
                    )
            except Exception as err:
                logging.error(f"Bad Request: {err!s}")
                if CREDENTIALS_REQUIRED is True:
                    raise web.HTTPClientError(
                        reason=err
                    )
            return await handler(request)
        return middleware
