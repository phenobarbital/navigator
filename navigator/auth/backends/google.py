"""GoogleAuth.

Description: Backend Authentication/Authorization using Google AUTH API.
"""
import base64
import rapidjson
import logging
import asyncio
import jwt
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from typing import List, Dict, Any
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from aiogoogle import Aiogoogle
from aiogoogle.auth.utils import create_secret
from navigator.conf import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_API_SCOPES,
    AUTH_SESSION_OBJECT
)

class GoogleAuth(BaseAuthBackend):
    """GoogleAuth.

    Authentication Backend using Google+aiogoogle.
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _credentials: Dict = {}
    google: Any = None

    def configure(self, app, router):
        # TODO: build the callback URL and append to routes
        self._credentials = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "scopes": GOOGLE_API_SCOPES,
            "redirect_uri": "http://localhost:5000/auth/complete/google-oauth2/",
        }
        self.google = Aiogoogle(
            client_creds=self._credentials
        )
        # add the callback url
        router = app.router
        router.add_route(
            "GET",
            "/auth/complete/google-oauth2/",
            self.finish_auth,
            name="google_complete_login"
        )
        router.add_route(
            "GET",
            "/api/v1/auth/google/",
            self.authenticate,
            name="google_api_login"
        )
        super(GoogleAuth, self).configure(app, router)

    async def get_payload(self, request):
        ctype = request.content_type
        if request.method == "GET":
            try:
                user = request.query.get(self.username_attribute, None)
                password = request.query.get(self.pwd_atrribute, None)
                return [user, password]
            except Exception:
                return None
        elif ctype in ("multipart/mixed", "application/x-www-form-urlencoded"):
            data = await request.post()
            if len(data) > 0:
                user = data.get(self.username_attribute, None)
                password = data.get(self.pwd_atrribute, None)
                return [user, password]
            else:
                return None
        elif ctype == "application/json":
            try:
                data = await request.json()
                user = data[self.username_attribute]
                password = data[self.pwd_atrribute]
                return [user, password]
            except Exception:
                return None
        else:
            return None

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        user = None
        try:
            user, pwd = await self.get_payload(request)
            print('USER', user, pwd)
        except Exception as err:
            print(err)
            # raise NavException(err, state=400)
            # making validation
        self._state = (
            create_secret()
        )  # Shouldn't be a global or a hardcoded variable. should be tied to a session or a user and shouldn't be used more than once
        self._nonce = (
            create_secret()
        )  # Shouldn't be a global or a hardcoded variable. should be tied to a session or a user and shouldn't be used more than once
        if self.google.openid_connect.is_ready(self._credentials):
            uri = self.google.openid_connect.authorization_url(
                client_creds=self._credentials,
                state=self._state,
                nonce=self._nonce,
                access_type="offline",
                include_granted_scopes=True,
                login_hint=user,
                prompt="select_account",
            )
            # Step A: redirect
            logging.debug(f'Google URI: {uri!s}')
            return web.HTTPFound(uri)
        else:
            raise NavException(
                "Client doesn't have info for Authentication"
            )

    async def finish_auth(self, request):
        try:
            if request.query.get('error'):
                error = {
                    "error": request.query.get("error"),
                    "error_description": request.query.get("error_description"),
                }
                print("Error HERE: ", err, err.state)
                response = {
                    "message": "Google Login Error",
                    **error
                }
                return web.json_response(response, status=403)
        except Exception as err:
            response = {
                "message": "Google Login Error"
            }
            return web.json_response(response, status=501)
        if code:=request.query.get("code"):
            state = request.query.get("state")
            if state != self._state:
                response = {
                    "message": "Something wrong with Authentication State",
                    "error": "Authenticate Error"
                }
                return web.json_response(response, status=403)
            user_creds = await self.google.openid_connect.build_user_creds(
                grant=code,
                client_creds=self._credentials,
                nonce=self._nonce,
                verify=False,
            )
            # print(user_creds)
            userdata = await self.google.openid_connect.get_user_info(
                user_creds
            )
            print(userdata)
            id = userdata['id']
            payload = {
                "user_id": id,
                **userdata
            }
            userdata[self.session_key_property] = id
            # saving Auth data.
            await self.remember(
                request, id, userdata
            )
            # Create the User session.
            token = self.create_jwt(data=payload)
            data = {
                "token": user_creds['id_token_jwt'],
                **userdata
            }
            # TODO: saving Auth token and user_creds on a Database
            return web.json_response(data, status=200)
        else:
            response = {
                "message": "Something wrong with Google Callback",
                "error": "Authenticate Error"
            }
            return web.json_response(response, status=403)

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
