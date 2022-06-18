"""OktaAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import logging
from aiohttp import web
from .oauth import OauthAuth
import requests
from navigator.conf import (
    OKTA_CLIENT_ID,
    OKTA_CLIENT_SECRET,
    OKTA_DOMAIN,
    OKTA_APP_NAME
)
from okta_jwt_verifier import JWTVerifier


async def is_token_valid(token, issuer, client_id):
    jwt_verifier = JWTVerifier(issuer, client_id, 'api://default')
    try:
        await jwt_verifier.verify_access_token(token)
        return True
    except Exception:
        return False


async def is_id_token_valid(token, issuer, client_id, nonce):
    jwt_verifier = JWTVerifier(issuer, client_id, 'api://default')
    try:
        await jwt_verifier.verify_id_token(token, nonce=nonce)
        return True
    except Exception:
        return False


class OktaAuth(OauthAuth):
    """OktaAuth.

    Description: Authentication Backend using Third-party Okta Service.
    """
    user_attribute: str = "user"
    username_attribute: str = "email"
    userid_attribute: str = "sub"
    pwd_atrribute: str = "password"
    _service_name: str = "okta"

    def configure(self, app, router, handler):
        super(OktaAuth, self).configure(app, router, handler) # first, configure parents

        # auth paths.
        self.base_url = f"https://{OKTA_DOMAIN}/"
        self.authorize_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/authorize"
        self.userinfo_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/userinfo"
        self._issuer = f"https://{OKTA_DOMAIN}/oauth2/default"
        self._token_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/token"
        self._introspection_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/introspect"

    async def get_credentials(self, request: web.Request):
        APP_STATE = 'ApplicationState'
        self.nonce = 'SampleNonce'
        domain_url = self.get_domain(request)
        self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
        qs = {
            "client_id": f"{OKTA_CLIENT_ID}",
            # "client_secret": f"{OKTA_CLIENT_SECRET}",
            "redirect_uri": self.redirect_uri,
            'scope': "openid email profile",
            'state': APP_STATE,
            'nonce': self.nonce,
            'response_type': 'code',
            'response_mode': 'query',
        }
        return qs

    async def auth_callback(self, request: web.Request):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        domain_url = self.get_domain(request)
        self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
        code = request.query.get("code")
        if not code:
            response = {
                "message": "Auth Error: Okta Code not accessible"
            }
            return web.json_response(response, status=403)
        # B.- processing the code
        query_params = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri
        }
        query_params = requests.compat.urlencode(query_params)
        try:
            exchange = requests.post(
                self._token_uri,
                headers=headers,
                data=query_params,
                auth=(
                    OKTA_CLIENT_ID,
                    OKTA_CLIENT_SECRET
                ),
            ).json()
        except Exception as err:
            response = {
                "message": f"Okta: Error Getting User Profile information: {err}"
            }
            return web.json_response(response, status=403)
        # Get tokens and validate
        if not exchange.get("token_type"):
            response = {
                "message": "Okta: Unsupported token type. Should be 'Bearer'."
            }
            return web.json_response(response, status=403)
        # user data
        access_token = exchange["access_token"]
        id_token = exchange["id_token"]

        if not await is_token_valid(access_token, self._issuer, OKTA_CLIENT_ID):
            response = {
                "message": "Okta: Access Token Invalid."
            }
            return web.json_response(response, status=403)

        if not await is_id_token_valid(id_token, self._issuer, OKTA_CLIENT_ID, self.nonce):
            response = {
                "message": "Okta: ID Token Invalid."
            }
            return web.json_response(response, status=403)

        # Authorization flow successful, get userinfo and login user
        try:
            data = requests.get(
                self.userinfo_uri,
                headers={'Authorization': f'Bearer {access_token}'}
            ).json()
            userdata, uid = self.build_user_info(data)
            # get user data
            data = await self.get_user_session(request, uid, userdata, access_token)
            return self.home_redirect(request, token=data['token'], token_type='Bearer')
        except Exception as err:
            logging.exception(f"Okta Auth Error: {err}")
            return self.redirect(uri=self.login_failed_uri)

    async def logout(self, request):
        pass

    async def finish_logout(self, request):
        pass

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
