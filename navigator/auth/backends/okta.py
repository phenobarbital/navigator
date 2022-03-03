"""OktaAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import rapidjson
import logging
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from typing import List, Dict, Any
import requests
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth,
    FailedAuth
)
from navigator.conf import (
    OKTA_CLIENT_ID,
    OKTA_CLIENT_SECRET,
    OKTA_DOMAIN,
    OKTA_APP_NAME,
    AUTH_SESSION_OBJECT
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

class OktaAuth(BaseAuthBackend):
    """OktaAuth.

    Description: Authentication Backend using Third-party Okta Service.
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _credentials: Dict = {}
    _okta: Any = None
    _uri: str = None
    nonce: Any = None

    def configure(self, app, router):
        self.base_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/authorize"
        self.redirect_uri = "http://nav-api.dev.local:5000/auth/complete/okta/"
        # async def _setup_okta(app):
        #     pass
        # asyncio.get_event_loop().run_until_complete(_setup_okta(app))
        # add the callback url
        router = app.router
        router.add_route(
            "GET",
            "/auth/complete/okta/",
            self.finish_auth,
            name="okta_complete_login"
        )
        router.add_route(
            "GET",
            "/api/v1/auth/okta/",
            self.authenticate,
            name="okta_api_login"
        )
        router.add_route(
            "GET",
            "/api/v1/auth/okta/logout",
            self.logout,
            name="okta_api_logout"
        )
        router.add_route(
            "GET",
            "/auth/okta/logout",
            self.finish_logout,
            name="okta_complete_logout"
        )
        self._issuer = f"https://{OKTA_DOMAIN}/oauth2/default"
        self._token_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/token"
        self._introspection_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/introspect"
        self._userinfo_uri = f"https://{OKTA_DOMAIN}/oauth2/default/v1/userinfo"
        # executing parent configurations
        super(OktaAuth, self).configure(app, router)

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
            # Build the URL
            APP_STATE = 'ApplicationState'
            self.nonce = 'SampleNonce'
            query_params = {
              "client_id": f"{OKTA_CLIENT_ID}",
              # "client_secret": f"{OKTA_CLIENT_SECRET}",
              "redirect_uri": self.redirect_uri,
              'scope': "openid email profile",
              'state': APP_STATE,
              'nonce': self.nonce,
              'response_type': 'code',
              'response_mode': 'query',
            }
            uri = "{base_uri}?{query_params}".format(
                base_uri=self.base_uri,
                query_params=requests.compat.urlencode(query_params)
            )
            # Step A: redirect
            logging.debug(f'Okta URI: {uri}')
            return web.HTTPFound(uri)
        except Exception as err:
            print('HERE: ', err)
            raise NavException(
                f"Client doesn't have info for Okta Authentication: {err}"
            )

    async def finish_auth(self, request):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        code = request.query.get("code")
        if not code:
            response = {
                "message": "Okta Code not accessible"
            }
            return web.json_response(response, status=403)
        # B.- processing the code
        query_params = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri
        }
        query_params = requests.compat.urlencode(query_params)
        print(query_params)
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
            print('ERR> ', err)
            response = {
                "message": "Okta: Error Getting User Profile information"
            }
            return web.json_response(response, status=403)
        print(exchange)
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
        userdata = requests.get(
            self._userinfo_uri,
            headers={'Authorization': f'Bearer {access_token}'}
        ).json()
        print(userdata)
        userdata['id'] = userdata["sub"]
        userdata[self.session_key_property] = userdata["sub"]
        userdata['access_token'] = access_token
        userdata['id_token'] = id_token
        # get user data
        # unique_id = userdata["sub"]
        # user_email = userdata["email"]
        # user_name = userdata["given_name"]
        # TODO: Optional: get User info from Nav
        payload = {
            "user_id": userdata["sub"],
            **userdata
        }
        # saving Auth data.
        await self.remember(
            request, userdata["sub"], userdata
        )
        # Create the User session.
        token = self.create_jwt(data=payload)
        data = {
            "token": token,
            "access_token": access_token,
            **userdata
        }
        # TODO: saving Auth token and user_creds on a Database
        return web.json_response(data, status=200)

    async def logout(self, request):
        pass

    async def finish_logout(self, request):
        pass

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
