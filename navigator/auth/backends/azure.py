"""GoogleAuth.

Description: Backend Authentication/Authorization using Google AUTH API.
"""
import logging
from aiohttp import web
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from navigator.conf import (
    AZURE_ADFS_CLIENT_ID,
    AZURE_ADFS_CLIENT_SECRET,
    AZURE_ADFS_SCOPES,
    AZURE_ADFS_DOMAIN,
    AZURE_ADFS_TENANT_ID
)
import msal
import json
import jwt
from .external import ExternalAuth
from typing import Any
from msal.authority import (
    AuthorityBuilder,
    AZURE_PUBLIC
)

class AzureAuth(ExternalAuth):
    """AzureAuth.

    Authentication Backend for Microsoft Online Services.
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _service_name: str = "azure"

    def configure(self, app, router, handler):
        super(AzureAuth, self).configure(app, router, handler)
        # TODO: build the callback URL and append to routes
        self.base_url: str = 'https://login.microsoftonline.com/{tenant}'.format(
            tenant=AZURE_ADFS_TENANT_ID
        )
        self.authorize_uri = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize".format(
            tenant=AZURE_ADFS_TENANT_ID
        )
        self.userinfo_uri = "https://graph.microsoft.com/v1.0/me"
        self._issuer = "https://login.microsoftonline.com/{tenant}".format(
            tenant=AZURE_ADFS_TENANT_ID
        )
        self._token_uri = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token".format(
            tenant=AZURE_ADFS_TENANT_ID
        )
        self.authority = AuthorityBuilder(AZURE_PUBLIC, "contoso.onmicrosoft.com")


    async def get_payload(self, request):
        pass
    
    def get_cache(self, request: web.Request):
        cache = msal.SerializableTokenCache()
        if request.get("token_cache"):
            cache.deserialize(request["token_cache"])
        return cache
    
    def save_cache(self, request: web.Request, cache):
        if cache.has_state_changed:
            request['token_cache'] = cache.serialize()
            
    def get_msal_app(self):
        authority = self._issuer if self._issuer else self.authority
        return msal.ConfidentialClientApplication(
            AZURE_ADFS_CLIENT_ID,
            authority=authority,
            client_credential = AZURE_ADFS_CLIENT_SECRET,
            validate_authority=True
            # token_cache=cache
        )

    async def authenticate(self, request: web.Request):
        """ Authenticate, refresh or return the user credentials."""
        authority = self._issuer if self._issuer else self.authority
        app = self.get_msal_app()
        SCOPE = ["https://graph.microsoft.com/.default"]
        try:
            flow = app.initiate_auth_code_flow(
                scopes=SCOPE,
                redirect_uri=self.redirect_uri,
                domain_hint=AZURE_ADFS_DOMAIN,
                max_age=120
            )
            async with await request.app['redis'].acquire() as redis:
                state = flow['state']
                await redis.setex(f'azure_auth_{state}', json.dumps(flow), timeout=120)
            login_url = flow['auth_uri']
            return self.redirect(login_url)
        except Exception as err:
            raise NavException(
                f"Azure: Client doesn't have info for Authentication: {err}"
            )


    async def auth_callback(self, request: web.Request):
        try:
            try:
                redis = request.app['redis']
            except Exception as err:
                raise Exception(
                    f'Azure Auth: Cannot get a Redis Cache connection: {err}'
                )
            auth_response = dict(request.rel_url.query.items())
            state = None
            SCOPE = ["https://graph.microsoft.com/.default"]
            try:
                state = auth_response['state']
            except Exception as err:
                raise Exception('Azure: Wrong authentication Callback, missing State.')
            try:
                async with await request.app['redis'].acquire() as redis:
                    result = await redis.get(f'azure_auth_{state}')
                    flow = json.loads(result)
            except Exception as err:
                raise Exception(f'Azure: Error reading Flow State from Cache: {err}')
            app = self.get_msal_app()
            try:
                result = app.acquire_token_by_auth_code_flow(
                    auth_code_flow=flow,
                    auth_response=auth_response
                )
                if 'token_type' in result:
                    token_type = result['token_type']
                    expires_in = result['expires_in']
                    access_token = result['access_token']
                    refresh_token = result['refresh_token']
                    id_token = result['id_token']
                    # logging.debug(f"Received access token: {id_token}")
                    # claims = jwt.decode(
                    #     id_token,
                    #     algorithms=['RS256', 'RS384', 'RS512'],
                    #     verify=False
                    # )
                    # print(f"JWT claims:\n {claims}")
                    claims = result['id_token_claims']
                    # getting user information:
                    try:
                        userdata = await self.get(url=self.userinfo_uri, token=access_token, token_type=token_type)
                        # build user information:
                        id = userdata['userPrincipalName']
                        userdata['id'] = id
                        userdata[self.session_key_property] = id
                        #userdata['access_token'] = access_token
                        userdata['id_token'] = id_token
                        #userdata['refresh_token'] = refresh_token
                        userdata['claims'] = claims
                        # also, user information:
                        userdata['email'] = userdata['userPrincipalName']
                        userdata['given_name'] = userdata['givenName']
                        userdata['family_name'] = userdata['surname']
                        data = await self.create_user(request, id, userdata, access_token)
                    except Exception as err:
                        logging.exception('Azure: Error getting User information')
                    # Redirect User to HOME
                    return self.home_redirect(request, token=data['token'], token_type=token_type)
                elif 'error' in result:
                    error = result['error']
                    desc = result['error_description']
                    message = f"Azure {error}: {desc}"
                    logging.exception(message)
                    response = {
                        "message": message
                    }
                    return web.json_response(response, status=403)
            except Exception as err:
                logging.exception(err)
                return self.redirect(uri=self.login_failed_uri)
        except Exception as err:
            logging.exception(err)
            return self.redirect(uri=self.login_failed_uri)

    async def logout(self, request):
        pass

    async def finish_logout(self, request):
        pass

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True
