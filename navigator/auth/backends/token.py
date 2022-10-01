"""Django Session Backend.

Navigator Authentication using API Token
description: Single API Token Authentication
"""
import logging
from typing import List
import jwt
from aiohttp import web
from navigator_session import get_session
from navigator.exceptions import NavException, InvalidAuth
from navigator.conf import (
    CREDENTIALS_REQUIRED,
    AUTH_JWT_ALGORITHM,
    AUTH_TOKEN_ISSUER,
    AUTH_TOKEN_SECRET
)
# Authenticated Entity
from navigator.auth.identities import AuthUser, Program
from .base import BaseAuthBackend

class TokenUser(AuthUser):
    tenant: str
    programs: List[Program]

class TokenAuth(BaseAuthBackend):
    """API Token Authentication Handler."""

    _pool = None
    _ident: AuthUser = TokenUser

    def configure(self, app, router, handler):
        super(TokenAuth, self).configure(app, router, handler)

    async def get_payload(self, request):
        token = None
        tenant = None
        id = None
        try:
            if "Authorization" in request.headers:
                try:
                    scheme, id = (
                        request.headers.get("Authorization").strip().split(" ", 1)
                    )
                except ValueError:
                    raise NavException(
                        "Invalid authorization Header",
                        state=400
                    )
                if scheme != self.scheme:
                    raise NavException(
                        "Invalid Authorization Scheme",
                        state=400
                    )
                try:
                    tenant, token = id.split(":")
                except ValueError:
                    token = id
        except Exception as err:
            logging.exception(f"TokenAuth: Error getting payload: {err}")
            return None
        return [tenant, token]

    async def reconnect(self):
        if not self.connection or not self.connection.is_connected():
            await self.connection.connection()

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        try:
            tenant, token = await self.get_payload(request)
            logging.debug(f"Tenant ID: {tenant}")
        except Exception as err:
            raise NavException(
                err, state=400
            ) from err
        if not token:
            raise InvalidAuth(
                "Invalid Credentials", state=401
            )
        else:
            payload = jwt.decode(
                token, AUTH_TOKEN_SECRET, algorithms=[AUTH_JWT_ALGORITHM], leeway=30
            )
            # logging.debug(f"Decoded Token: {payload!s}")
            data = await self.check_token_info(request, tenant, payload)
            if not data:
                raise InvalidAuth(
                    f"Invalid Session: {token!s}", state=401
                )
            # getting user information
            # making validation
            try:
                u = data["name"]
                username = data["partner"]
                grants = data["grants"]
                programs = data["programs"]
            except KeyError as err:
                print(err)
                raise InvalidAuth(
                    f"Missing attributes for Partner Token: {err!s}",
                    state=401
                ) from err
            # TODO: Validate that partner (tenants table):
            try:
                userdata = dict(data)
                id = data["name"]
                user = {
                    "name": data["name"],
                    "partner": username,
                    "issuer": AUTH_TOKEN_ISSUER,
                    "programs": programs,
                    "grants": grants,
                    "tenant": tenant,
                    "id": data["name"],
                    "user_id": id,
                }
                userdata[self.session_key_property] = id
                usr = await self.create_user(userdata)
                usr.id = id
                usr.set(self.username_attribute, id)
                usr.programs = programs
                usr.tenant = tenant
                logging.debug(f'User Created: {usr}')
                token = self.create_jwt(data=user)
                usr.access_token = token
                # saving user-data into request:
                await self.remember(
                    request, id, userdata, usr
                )
                return {
                    "token": f"{tenant}:{token}",
                    **user
                }
            except Exception as err:
                logging.exception(f'DjangoAuth: Authentication Error: {err}')
                return False

    async def check_credentials(self, request):
        pass

    async def check_token_info(self, request, tenant, payload):
        try:
            name = payload["name"]
            partner = payload["partner"]
        except KeyError as err:
            return False
        sql = """
        SELECT name, partner, grants, programs FROM troc.api_keys
        WHERE name=$1 AND partner=$2
        AND enabled = TRUE AND revoked = FALSE AND $3= ANY(programs)
        """
        app = request.app
        pool = app['database']
        try:
            result = None
            async with await pool.acquire() as conn:
                result, error = await conn.queryrow(sql, name, partner, tenant)
                if error or not result:
                    return False
                else:
                    return result
        except Exception as err:
            logging.exception(err)
            return False

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            logging.debug(f'MIDDLEWARE: {self.__class__.__name__}')
            request.user = None
            try:
                authz = await self.authorization_backends(app, handler, request)
                if authz:
                    return await handler(request)
            except Exception as err:
                logging.exception(
                    f'Error Processing Base Authorization Backend: {err!s}'
                )
            try:
                auth = request.get('authenticated', False)
                if auth is True:
                    # already authenticated
                    return await handler(request)
            except KeyError:
                pass
            tenant, jwt_token = await self.get_payload(request)
            if jwt_token:
                try:
                    payload = jwt.decode(
                        jwt_token, AUTH_TOKEN_SECRET, algorithms=[AUTH_JWT_ALGORITHM], leeway=30
                    )
                    # logging.debug(f"Decoded Token: {payload!s}")
                    result = await self.check_token_info(request, tenant, payload)
                    if not result:
                        if CREDENTIALS_REQUIRED is True:
                            raise web.HTTPForbidden(
                                reason="API Key Not Authorized",
                            )
                    else:
                        request[self.session_key_property] = payload['name']
                        # TRUE because if data doesnt exists, returned
                        session = await get_session(request, payload, new = True)
                        print('::::: SESSION: ', session)
                        session["grants"] = result["grants"]
                        session["partner"] = result["partner"]
                        session["tenant"] = tenant
                        try:
                            request.user = session.decode('name')
                            request.user.is_authenticated = True
                        except KeyError:
                            pass
                        # print('USER> ', request.user, type(request.user))
                        request['authenticated'] = True
                except (jwt.exceptions.ExpiredSignatureError) as err:
                    logging.error(f"TokenAuth: token expired: {err!s}")
                except (jwt.exceptions.InvalidSignatureError) as err:
                    logging.error(f"Invalid Credentials: {err!r}")
                except (jwt.exceptions.DecodeError, jwt.exceptions.InvalidTokenError) as err:
                    logging.error(f"Invalid authorization token: {err!r}")
                except Exception as err:
                    logging.exception(f"Error on Token Middleware: {err}")
            return await handler(request)

        return middleware
