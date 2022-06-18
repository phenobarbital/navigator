"""GoogleAuth.

Description: Backend Authentication/Authorization using Google AUTH API.
"""
import logging
from aiohttp import web
from navigator.exceptions import (
    NavException
)
from aiogoogle import Aiogoogle
from aiogoogle.auth.utils import create_secret
from navigator.conf import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_API_SCOPES
)
from .external import ExternalAuth


class GoogleAuth(ExternalAuth):
    """GoogleAuth.

    Authentication Backend using Google+aiogoogle.
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _service_name: str = "google"

    def configure(self, app, router, handler):
        super(GoogleAuth, self).configure(app, router, handler)
        # TODO: build the callback URL and append to routes
        self._credentials = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "scopes": GOOGLE_API_SCOPES,
            "redirect_uri": self.redirect_uri,
        }


    async def get_payload(self, request):
        pass

    async def authenticate(self, request):
        """ Authenticate, refresh or return the user credentials."""
        self._state = (
            create_secret()
        )  # Shouldn't be a global or a hardcoded variable. should be tied to a session or a user and shouldn't be used more than once
        self._nonce = (
            create_secret()
        )  # Shouldn't be a global or a hardcoded variable. should be tied to a session or a user and shouldn't be used more than once
        domain_url = self.get_domain(request)
        self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
        self._credentials["redirect_uri"] = self.redirect_uri
        self.google = Aiogoogle(
            client_creds=self._credentials
        )
        if self.google.openid_connect.is_ready(self._credentials):
            uri = self.google.openid_connect.authorization_url(
                client_creds=self._credentials,
                state=self._state,
                nonce=self._nonce,
                access_type="offline",
                include_granted_scopes=True,
                # login_hint=user,
                prompt="select_account",
            )
            # Step A: redirect
            return self.redirect(uri)
        else:
            raise NavException(
                "Client doesn't have info for Authentication"
            )

    async def auth_callback(self, request: web.Request):
        try:
            if request.query.get('error'):
                error = {
                    "error": request.query.get("error"),
                    "error_description": request.query.get("error_description"),
                }
                logging.exception(f"Google Login Error: {err}, {err.state}")
                response = {
                    "message": "Google Login Error",
                    **error
                }
                return web.json_response(response, status=403)
        except Exception as err:
            logging.exception(f"Google Login Error: {err}, {err.state}")
            response = {
                "message": f"Google Login Error: {err}, {err.state}"
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
            try:
                id = userdata['id']
                access_token = user_creds['id_token_jwt']
                userdata[self.session_key_property] = id
                data = await self.get_user_session(request, id, userdata, access_token)
                return self.home_redirect(request, token=data['token'], token_type='Bearer')
            except Exception as err:
                logging.exception(f"Google Auth Error: {err}")
                return self.redirect(uri=self.login_failed_uri)
        else:
            response = {
                "message": "Something wrong with Google Callback",
                "error": "Authenticate Error"
            }
            return web.json_response(response, status=403)

    async def logout(self, request):
        pass

    async def finish_logout(self, request):
        pass

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
