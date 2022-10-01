"""TROC Backend.

Troc Authentication using RNC algorithm.
"""
import logging
from aiohttp import web
import orjson
from navigator_session import AUTH_SESSION_OBJECT
from navigator.libs.cypher import Cipher
from navigator.exceptions import (
    NavException,
    UserNotFound,
    InvalidAuth
)
from navigator.conf import (
    PARTNER_KEY,
    CYPHER_TYPE
)
from .base import BaseAuthBackend
from .basic import BasicUser


# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)


class TrocToken(BaseAuthBackend):
    """TROC authentication Header."""

    user_attribute: str = "user"
    username_attribute: str = "email"
    _ident: BasicUser = BasicUser

    def __init__(
        self,
        user_attribute: str = None,
        userid_attribute: str = None,
        password_attribute: str = None,
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        super().__init__(
            user_attribute,
            userid_attribute,
            password_attribute,
            credentials_required,
            authorization_backends,
            **kwargs,
        )
        # forcing to use Email as Username Attribute
        self.username_attribute = "email"

    def configure(self, app, router, handler):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""

    async def validate_user(self, login: str = None):
        # get the user based on Model
        search = {self.username_attribute: login}
        try:
            user = await self.get_user(**search)
            return user
        except UserNotFound as err:
            raise UserNotFound(
                f"User {login} doesn't exists"
            ) from err
        except Exception as err:
            logging.exception(err)
            raise

    async def get_payload(self, request):
        troctoken = None
        try:
            if "Authorization" in request.headers:
                try:
                    scheme, token = (
                        request.headers.get("Authorization").strip().split(" ")
                    )
                except ValueError:
                    raise web.HTTPForbidden(
                        reason="Invalid authorization Header",
                    )
                if scheme != self.scheme:
                    raise web.HTTPForbidden(
                        reason="Invalid Session scheme",
                    )
            else:
                try:
                    token = request.query.get("auth", None)
                except Exception as e:
                    print(e)
                    return None
        except Exception as err:
            logging.exception(f"TrocAuth: Error getting payload: {err}")
            return None
        return token

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        try:
            token = await self.get_payload(request)
        except Exception as err:
            raise NavException(
                err, state=400
            ) from err
        if not token:
            raise InvalidAuth(
                "Missing Credentials",
                state=401
            )
        else:
            # getting user information
            # TODO: making the validation of token and expiration
            try:
                data = orjson.loads(CIPHER.decode(passphrase=token))
                logging.debug(
                    f'TrocToken: Decoded User data: {data!r}'
                )
            except Exception as err:
                raise InvalidAuth(
                    f"Invalid Token: {err!s}", state=401
                ) from err
            # making validation
            try:
                username = data[self.username_attribute]
            except KeyError as err:
                raise InvalidAuth(
                    f"Missing Email attribute: {err!s}", state=401
                ) from err
            try:
                user = await self.validate_user(login=username)
            except UserNotFound as err:
                raise UserNotFound(err) from err
            except Exception as err:
                raise NavException(err, state=500) from err
            try:
                userdata = self.get_userdata(user)
                try:
                    # merging both session objects
                    userdata[AUTH_SESSION_OBJECT] = {
                        **userdata[AUTH_SESSION_OBJECT], **data
                    }
                except Exception as err:
                    logging.exception(err)
                id = user[self.username_attribute]
                username = user[self.username_attribute]
                userdata[self.session_key_property] = id
                usr = await self.create_user(
                    userdata[AUTH_SESSION_OBJECT]
                )
                usr.id = id
                usr.set(self.username_attribute, username)
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: username,
                    "user_id": user[self.userid_attribute],
                }
                token = self.create_jwt(data=payload)
                usr.access_token = token
                # saving user-data into request:
                await self.remember(
                    request, id, userdata, usr
                )
                return {
                    "token": token,
                    **userdata
                }
            except Exception as err:
                logging.exception(f'DjangoAuth: Authentication Error: {err}')
                return False

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
