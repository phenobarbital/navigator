"""ADFSAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import logging
import base64
from aiohttp import web
from .external import ExternalAuth
from typing import Dict
import jwt
from .jwksutils import get_public_key
# needed by ADFS
import requests
import requests.adapters
from navigator.exceptions import (
    NavException
)
from navigator.conf import (
    ADFS_SERVER,
    ADFS_CLIENT_ID,
    ADFS_TENANT_ID,
    ADFS_RESOURCE,
    ADFS_AUDIENCE,
    ADFS_SCOPES,
    ADFS_ISSUER,
    USERNAME_CLAIM,
    GROUP_CLAIM,
    ADFS_CLAIM_MAPPING,
    ADFS_CALLBACK_REDIRECT_URL,
    ADFS_LOGIN_REDIRECT_URL,
    AZURE_AD_SERVER
)

_jwks_cache = {}

class ADFSAuth(ExternalAuth):
    """ADFSAuth.

    Description: Authentication Backend using
    Active Directory Federation Service (ADFS).
    """
    _service_name: str = "adfs"
    user_attribute: str = "user"
    userid_attribute: str = 'upn'
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    version = 'v1.0'
    _user_mapping: Dict = {
        'user_id': 'upn',
        'email': 'email',
        'given_name': 'given_name',
        'family_name': 'family_name',
        'groups': "group",
        'department': 'Department',
        'name': 'Display-Name'
    }

    def configure(self, app, router, handler):
        super(ADFSAuth, self).configure(app, router, handler)
        # URIs:
        if ADFS_TENANT_ID:
            self.server = AZURE_AD_SERVER
            self.tenant_id = ADFS_TENANT_ID
            self.username_claim = "upn"
            self.groups_claim = "groups"
            self.claim_mapping = ADFS_CLAIM_MAPPING
            self.discovery_oid_uri = f'https://login.microsoftonline.com/{self.tenant_id}/.well-known/openid-configuration'
        else:
            self.server = ADFS_SERVER
            self.tenant_id = 'adfs'
            self.username_claim = USERNAME_CLAIM
            self.groups_claim = GROUP_CLAIM
            self.claim_mapping = ADFS_CLAIM_MAPPING
            self.discovery_oid_uri = f'https://{self.server}/adfs/.well-known/openid-configuration'
            self._discovery_keys_uri = f'https://{self.server}/adfs/discovery/keys'

        self.base_uri = f"https:://{self.server}/"
        self.end_session_endpoint = f"https://{self.server}/{self.tenant_id}/ls/?wa=wsignout1.0"
        self._issuer = f"https://{self.server}/{self.tenant_id}/services/trust"
        self.authorize_uri = f"https://{self.server}/{self.tenant_id}/oauth2/authorize/"
        self._token_uri = f"https://{self.server}/{self.tenant_id}/oauth2/token"
        self.userinfo_uri = f"https://{self.server}/{self.tenant_id}/userinfo"

        if ADFS_LOGIN_REDIRECT_URL is not None:
            login = ADFS_LOGIN_REDIRECT_URL
        else:
            login = f"/api/v1/auth/{self._service_name}/"

        if ADFS_CALLBACK_REDIRECT_URL is not None:
            callback = ADFS_CALLBACK_REDIRECT_URL
            self.redirect_uri = "{domain}" + callback
        else:
            callback = f"/auth/{self._service_name}/callback/"
        # Login and Redirect Routes:
        router.add_route(
            "*",
            login,
            self.authenticate,
            name=f"{self._service_name}_login"
        )
        # finish login (callback)
        router.add_route(
            "*",
            callback,
            self.auth_callback,
            name=f"{self._service_name}_callback_login"
        )

    async def authenticate(self, request: web.Request):
        """ Authenticate, refresh or return the user credentials.

        Description: This function returns the ADFS authorization URL.
        """
        domain_url = self.get_domain(request)
        self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
        try:
            self.state = base64.urlsafe_b64encode(self.redirect_uri.encode()).decode()
            query_params = {
                "client_id": ADFS_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "resource": ADFS_RESOURCE,
                "response_mode": "query",
                "state": self.state,
                "scope": ADFS_SCOPES
            }
            params = requests.compat.urlencode(query_params)
            login_url = f"{self.authorize_uri}?{params}"
            # Step A: redirect
            return self.redirect(login_url)
        except Exception as err:
            logging.exception(err)
            raise NavException(
                f"Client doesn't have info for ADFS Authentication: {err}"
            ) from err

    async def auth_callback(self, request: web.Request):
        domain_url = self.get_domain(request)
        self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
        try:
            auth_response = dict(request.rel_url.query.items())
            authorization_code = auth_response['code']
            state = auth_response['state'] # TODO: making validation with previous state
            request_id = auth_response['client-request-id']
        except Exception as err:
            print(err)
            raise NavException(
                f"ADFS: Invalid Callback response: {err}"
            ) from err
        # print(authorization_code, state, request_id)
        logging.debug("Received authorization token: %s", authorization_code)
        # getting an Access Token
        query_params = {
            "code": authorization_code,
            "client_id": ADFS_CLIENT_ID,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "scope": ADFS_SCOPES
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        try:
            exchange = await self.post(self._token_uri, data=query_params, headers=headers)
            if 'error' in exchange:
                error = exchange.get('error')
                desc = exchange.get('error_description')
                message = f"Azure {error}: {desc}¡"
                logging.exception(message)
                raise web.HTTPForbidden(
                    reason=message
                )
            else:
                ## processing the exchange response:
                access_token = exchange["access_token"]
                token_type = exchange["token_type"] # ex: Bearer
                id_token = exchange["id_token"]
                logging.debug(f"Received access token: {access_token}")
                # decipher the Access Token:
                # getting user information:
                options = {
                    'verify_signature': True,
                    'verify_exp': True,
                    'verify_nbf': True,
                    'verify_iat': True,
                    'verify_aud': True,
                    'verify_iss': True,
                    'require_exp': False,
                    'require_iat': False,
                    'require_nbf': False
                }
                public_key = get_public_key(access_token, self.tenant_id, self.discovery_oid_uri)
                # Validate token and extract claims
                data = jwt.decode(
                    access_token,
                    key=public_key,
                    algorithms=['RS256', 'RS384', 'RS512'],
                    verify=True,
                    audience=ADFS_AUDIENCE,
                    issuer=ADFS_ISSUER,
                    options=options,
                )
                try:
                    # build user information:
                    try:
                        data = await self.get(url=self.userinfo_uri, token=access_token, token_type=token_type)
                    except Exception as err:
                        logging.error(err)
                    print('USER DATA: ', data)
                    userdata, uid = self.build_user_info(data)
                    userdata['id_token'] = id_token
                    data = await self.get_user_session(request, uid, userdata, access_token)
                except Exception as err:
                    logging.exception(f'ADFS: Error getting User information: {err}')
                    raise web.HTTPForbidden(
                        reason=f"ADFS: Error with User Information: {err}"
                    )
                # Redirect User to HOME
                return self.home_redirect(request, token=data['token'], token_type='Bearer')
        except Exception as err:
            raise web.HTTPForbidden(
                reason=f"ADFS: Invalid Response from Server {err}."
            )

    async def logout(self, request):
        # first: removing the existing session
        # second: redirect to SSO logout
        logging.debug(f'ADFS LOGOUT URI: {self.end_session_endpoint}')
        return web.HTTPFound(self.end_session_endpoint)

    async def finish_logout(self, request):
        pass

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
