"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import logging
import hashlib
import base64
import secrets
from .base import BaseAuthBackend
from navigator.exceptions import (
    NavException,
    FailedAuth,
    UserNotFound,
    InvalidAuth,
    ValidationError,
)
from navigator.conf import (
    AUTH_PWD_DIGEST,
    AUTH_PWD_ALGORITHM,
    AUTH_PWD_LENGTH,
    AUTH_PWD_SALT_LENGTH
)
# Authenticated Entity
from navigator.auth.identities import AuthUser
from navigator_session import AUTH_SESSION_OBJECT


class BasicUser(AuthUser):
    """BasicAuth.

    Basic authenticated user.
    """


# "%s$%d$%s$%s" % (algorithm, iterations, salt, hash)


class BasicAuth(BaseAuthBackend):
    """Basic User/password Authentication."""

    user_attribute: str = "user"
    pwd_atrribute: str = "password"
    _ident: AuthUser = BasicUser

    def configure(self, app, router, handler):
        """Base configuration for Auth Backends, need to be extended
        to create Session Object."""

    async def validate_user(self, login: str = None, password: str = None):
        # get the user based on Model
        try:
            search = {self.username_attribute: login}
            user = await self.get_user(**search)
        except UserNotFound as err:
            raise UserNotFound(
                f"User {login} doesn't exists"
            ) from err
        except Exception as err:
            raise Exception from err
        try:
            # later, check the password
            pwd = user[self.pwd_atrribute]
        except KeyError:
            raise ValidationError(
                'NAV: Missing Password attr on User Account'
            )
        try:
            if self.check_password(pwd, password):
                # return the user Object
                return user
            else:
                raise FailedAuth(
                    "Basic Auth: Invalid Credentials"
                )
        except Exception as err:
            raise Exception from err

    def set_password(
        self,
        password: str,
        token_num: int = 6,
        iterations: int = 80000,
        salt: str = None
    ):
        if not salt:
            salt = secrets.token_hex(token_num)
        key = hashlib.pbkdf2_hmac(
            AUTH_PWD_DIGEST,
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
            dklen=AUTH_PWD_LENGTH,
        )
        hst = base64.b64encode(key).decode("utf-8").strip()
        return f"{AUTH_PWD_ALGORITHM}${iterations}${salt}${hst}"

    def check_password(self, current_password, password):
        try:
            algorithm, iterations, salt, hash = current_password.split("$", 3)
        except ValueError:
            raise InvalidAuth(
                'Basic Auth: Invalid Password Algorithm'
            )
        assert algorithm == AUTH_PWD_ALGORITHM
        compare_hash = self.set_password(
            password,
            iterations=int(iterations),
            salt=salt,
            token_num=AUTH_PWD_SALT_LENGTH
        )
        return secrets.compare_digest(current_password, compare_hash)

    async def get_payload(self, request):
        ctype = request.content_type
        if request.method == "GET":
            try:
                user = request.query.get(self.username_attribute, None)
                password = request.query.get(self.pwd_atrribute, None)
                return [user, password]
            except Exception:
                return [None, None]
        elif ctype in ("multipart/mixed", "multipart/form-data", "application/x-www-form-urlencoded"):
            data = await request.post()
            if len(data) > 0:
                user = data.get(self.username_attribute, None)
                password = data.get(self.pwd_atrribute, None)
                return [user, password]
            else:
                return [None, None]
        elif ctype == "application/json":
            try:
                data = await request.json()
                user = data[self.username_attribute]
                password = data[self.pwd_atrribute]
                return [user, password]
            except Exception:
                return [None, None]
        else:
            return [None, None]

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        try:
            user, pwd = await self.get_payload(request)
        except Exception as err:
            raise NavException(err, state=400) from err
        if not pwd and not user:
            raise InvalidAuth(
                "Basic Auth: Invalid Credentials",
                state=401
            )
        else:
            # making validation
            try:
                user = await self.validate_user(login=user, password=pwd)
            except FailedAuth as err:
                raise FailedAuth(err) from err
            except UserNotFound as err:
                raise UserNotFound(err) from err
            except (ValidationError, InvalidAuth) as err:
                raise InvalidAuth(err, state=401) from err
            except Exception as err:
                raise NavException(
                    err, state=500
                ) from err
            try:
                userdata = self.get_userdata(user)
                username = user[self.username_attribute]
                id = user[self.userid_attribute]
                userdata[self.username_attribute] = username
                userdata[self.session_key_property] = username
                # usr = BasicUser(data=userdata[AUTH_SESSION_OBJECT])
                usr = await self.create_user(
                    userdata[AUTH_SESSION_OBJECT]
                )
                usr.id = id
                usr.set(self.username_attribute, username)
                logging.debug(f'User Created > {usr}')
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: username,
                    "user_id": id,
                    self.session_key_property: username
                }
                # Create the User session and returned.
                token = self.create_jwt(data=payload)
                usr.access_token = token
                await self.remember(
                    request, username, userdata, usr
                )
                return {
                    "token": token,
                    **userdata
                }
            except Exception as err:
                logging.exception(f'DjangoAuth: Authentication Error: {err}')
                return False

    async def check_credentials(self, request):
        """ Using for check the user credentials to the backend."""
