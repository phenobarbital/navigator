"""JWT Backend.

Navigator Authentication using JSON Web Tokens.
"""
import jwt
import hashlib
import base64
import secrets
from aiohttp import web
from .base import BaseAuthBackend
from datetime import datetime, timedelta
from navigator.exceptions import (
    NavException,
    FailedAuth,
    UserDoesntExists,
    InvalidAuth
)
from navigator.conf import (
    SESSION_TIMEOUT,
    SECRET_KEY,
    AUTH_PWD_DIGEST,
    AUTH_PWD_ALGORITHM,
    AUTH_PWD_LENGTH,
    AUTH_PWD_SALT_LENGTH
)
# "%s$%d$%s$%s" % (algorithm, iterations, salt, hash)


class BasicAuth(BaseAuthBackend):
    """Basic User/password Authentication."""

    user_attribute: str = "user"
    pwd_atrribute: str = "password"

    async def validate_user(self, login: str = None, password: str = None):
        # get the user based on Model
        try:
            search = {self.username_attribute: login}
            user = await self.get_user(**search)
        except UserDoesntExists as err:
            raise UserDoesntExists(
                f"User {login} doesn't exists"
            )
        except Exception:
            raise
        try:
            # later, check the password
            pwd = user[self.pwd_atrribute]
        except KeyError:
            raise ValidationError(
                'Missing Password attribute on User Account'
            )
        try:
            if self.check_password(pwd, password):
                # return the user Object
                return user
            else:
                raise FailedAuth(
                    "Basic Auth: Invalid Credentials"
                )
        except Exception:
            raise
        return None

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
        hash = base64.b64encode(key).decode("utf-8").strip()
        return f"{AUTH_PWD_ALGORITHM}${iterations}${salt}${hash}"

    def check_password(self, current_password, password):
        try:
            algorithm, iterations, salt, hash = current_password.split("$", 3)
        except ValueError:
            raise InvalidAuth('Basic Auth: Invalid Password Algorithm')
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
            raise NavException(err, state=400)
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
                raise FailedAuth(err)
            except UserDoesntExists as err:
                raise UserDoesntExists(err)
            except (ValidationError, InvalidAuth) as err:
                raise InvalidAuth(err, state=401)
            except Exception as err:
                raise NavException(
                    err, state=500
                )
            try:
                userdata = self.get_userdata(user)
                username = user[self.username_attribute]
                id = user[self.userid_attribute]
                userdata[self.username_attribute] = username
                userdata[self.session_key_property] = username
                payload = {
                    self.user_property: user[self.userid_attribute],
                    self.username_attribute: username,
                    "user_id": id,
                    self.session_key_property: username
                }
                await self.remember(
                    request, username, userdata
                )
                # Create the User session and returned.
                token = self.create_jwt(data=payload)
                return {
                    "token": token,
                    **userdata
                }
            except Exception as err:
                return False

    async def check_credentials(self, request):
        """ Using for check the user credentials to the backend."""
        pass
