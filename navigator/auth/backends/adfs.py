"""ADFSAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import rapidjson
import logging
import asyncio
import base64
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from typing import List, Dict, Any
import jwt
# needed by ADFS
from xml.etree import ElementTree
import requests
import requests.adapters
from urllib3.util.retry import Retry
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.x509 import load_der_x509_certificate

from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth,
    FailedAuth
)
from navigator.conf import (
    ADFS_SERVER,
    ADFS_CLIENT_ID,
    ADFS_RELYING_PARTY_ID,
    ADFS_TENANT_ID,
    ADFS_RESOURCE,
    ADFS_AUDIENCE,
    ADFS_ISSUER,
    USERNAME_CLAIM,
    GROUP_CLAIM,
    ADFS_CLAIM_MAPPING,
    ADFS_LOGIN_REDIRECT_URL,
    AZURE_AD_SERVER
)


def load_certs():
    """Extract token signing certificates."""
    xml_tree = ElementTree.fromstring(response.content)
    cert_nodes = xml_tree.findall(
            "./{urn:oasis:names:tc:SAML:2.0:metadata}RoleDescriptor"
            "[@{http://www.w3.org/2001/XMLSchema-instance}type='fed:SecurityTokenServiceType']"
            "/{urn:oasis:names:tc:SAML:2.0:metadata}KeyDescriptor[@use='signing']"
            "/{http://www.w3.org/2000/09/xmldsig#}KeyInfo"
            "/{http://www.w3.org/2000/09/xmldsig#}X509Data"
            "/{http://www.w3.org/2000/09/xmldsig#}X509Certificate"
    )
    signing_certificates = [node.text for node in cert_nodes]
    new_keys = []
    for cert in signing_certificates:
        logging.debug("Loading public key from certificate: %s", cert)
        cert_obj = load_der_x509_certificate(
            base64.b64decode(cert), backend
        )
        new_keys.append(
            cert_obj.public_key()
        )
    return new_keys

class ADFSAuth(BaseAuthBackend):
    """ADFSAuth.

    Description: Authentication Backend using
    Active Directory Federation Service (ADFS).
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _credentials: Dict = {}
    _adfs: Any = None
    version = 'v1.0'

    def configure(self, app, router, handler):
        # URIs:
        router = app.router
        if ADFS_TENANT_ID:
            self.server = AZURE_AD_SERVER
            self.tenant_id = ADFS_TENANT_ID
            self.username_claim = "upn"
            self.groups_claim = "groups"
            self.claim_mapping = ADFS_CLAIM_MAPPING
        else:
            self.server = ADFS_SERVER
            self.tenant_id = 'adfs'
            self.username_claim = USERNAME_CLAIM
            self.groups_claim = GROUP_CLAIM
            self.claim_mapping = ADFS_CLAIM_MAPPING
        self.base_uri = f"https:://{self.server}/"
        self.end_session_endpoint = f"https://{self.server}/{self.tenant_id}/ls/?wa=wsignout1.0"
        self.issuer = f"https://{self.server}/{self.tenant_id}/services/trust"
        self.authorization_endpoint = f"https://{self.server}/{self.tenant_id}/oauth2/authorize/"
        self.token_endpoint = f"https://{self.server}/{self.tenant_id}/oauth2/token"
        async def _setup_adfs(app):
            pass
        asyncio.get_event_loop().run_until_complete(_setup_adfs(app))
        # creating the Paths
        router.add_route(
            "GET",
            "/auth/adfs/callback",
            self.finish_auth,
            name="adfs_complete_login"
        )
        router.add_route(
            "GET",
            "/auth/adfs/login",
            self.authenticate,
            name="adfs_api_login"
        )
        router.add_route(
            "GET",
            "/auth/adfs/logout",
            self.logout,
            name="adfs_api_logout"
        )
        router.add_route(
            "GET",
            "/auth/adfs/complete_logout",
            self.finish_logout,
            name="adfs_complete_logout"
        )
        # executing parent configurations
        super(ADFSAuth, self).configure(app, router, handler)

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
        """ Authenticate, refresh or return the user credentials.

        Description: This function returns the ADFS authorization URL.
        """
        app = request.app
        # print(app)
        absolute_uri = str(request.url)
        print('URL: ', absolute_uri)
        domain_url = absolute_uri.replace(str(request.rel_url), '')
        print('DOMAIN: ', domain_url)
        self.end_authorization_endpoint = f"{domain_url}/auth/adfs/callback"
        try:
            self.redirect_uri = "{}{}".format(
                domain_url,
                app.router["home"].url_for()
            )
        except Exception as err:
            print(err)
            self.redirect_uri = ADFS_LOGIN_REDIRECT_URL
        print('REDIRECT: ', self.redirect_uri)
        try:
            self.state = base64.urlsafe_b64encode(self.redirect_uri.encode()).decode()
            query_params = {
                "client_id": ADFS_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": self.end_authorization_endpoint,
                "resource": ADFS_RESOURCE,
                "response_mode": "query",
                "state": self.state,
                "scope": "openid",
                "grant_type": "client_credentials"
            }
            uri = "{base_uri}?{query_params}".format(
                base_uri=self.authorization_endpoint,
                query_params=requests.compat.urlencode(query_params)
            )
            # Step A: redirect
            logging.debug(f'ADFS URI: {uri}')
            return web.HTTPFound(uri)
        except Exception as err:
            print('HERE: ', err)
            raise NavException(
                f"Client doesn't have info for ADFS Authentication: {err}"
            )

    async def finish_auth(self, request):
        # self.end_authorization_endpoint = "http://navigator.dev.mobileinsight.com/oauth2/callback"
        try:
            response = {key: val for (key, val) in request.query.items()}
            authorization_code = response['code']
            state = response['state']
            request_id = response['client-request-id']
        except Exception as err:
            print(err)
            raise NavException(
                f"ADFS: Invalid Callback response: {err}"
            )
        print(authorization_code, state, request_id)
        logging.debug("Received authorization token: " + code)
        # getting an Access Token
        query_params = {
            "client_id": ADFS_CLIENT_ID,
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.end_authorization_endpoint
        }
        query_params = requests.compat.urlencode(query_params)
        print(query_params)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        try:
            exchange = requests.post(
                self.token_endpoint,
                headers=headers,
                data=query_params
            )
            if exchange.status_code == 400:
                logging.error("ADFS server returned an error: " + exchange.json()["error_description"])
                # raise PermissionDenied

            if exchange.status_code != 200:
                logging.error("Unexpected ADFS response: " + exchange.content.decode())
                # raise PermissionDenied
            ## processing the exchange response:
            response = exchange.json()
            access_token = response["access_token"]
            token_type = response["token_type"] # ex: Bearer
            id_token = response["id_token"]
            logging.debug(f"Received access token: {access_token}")
            claims = jwt.decode(
                id_token,
                algorithms=['RS256', 'RS384', 'RS512'],
                verify=False
            )
            logging.debug(f"JWT claims:\n {claims}")
            claims = None
            # validate:
            #
        except Exception as err:
            print(err)
        return web.Response(body="Hello World")

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
