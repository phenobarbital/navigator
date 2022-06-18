"""OktaAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import logging
from aiohttp import web
from .oauth import OauthAuth
from navigator.conf import (
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET
)


class GithubAuth(OauthAuth):
    """GithubAuth.

    Description: Authentication Backend using Third-party GitHub Service.
    """
    userid_attribute: str = "login"
    user_attribute: str = "name"
    username_attribute: str = "email"
    _service_name: str = "github"

    def configure(self, app, router, handler):
        super(GithubAuth, self).configure(app, router, handler) # first, configure parents

        # auth paths.
        self.base_url = 'https://api.github.com/'
        self.authorize_uri = 'https://github.com/login/oauth/authorize'
        self.userinfo_uri = 'https://api.github.com/user'
        self._issuer = 'https://api.github.com/'
        self._token_uri = 'https://github.com/login/oauth/access_token'


    async def get_credentials(self, request: web.Request):
        qs = {
            "client_id": f"{GITHUB_CLIENT_ID}",
            "client_secret": GITHUB_CLIENT_SECRET,
            "scope": "user:email"
        }
        return qs

    async def auth_callback(self, request: web.Request):
        try:
            auth_response = self.get_auth_response(request)
            code = self.get_auth_code(auth_response)
        except Exception as err:
            message = f"Github: Missing Auth Token: {auth_response}"
            logging.exception(message)
            response = {
                "message": message
            }
            return web.json_response(response, status=403)
        grant = {
            "client_id": f"{GITHUB_CLIENT_ID}",
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            'scope': "user:email"
        }
        result = await self.post(self._token_uri, json=grant)
        if 'error' in result:
            message = f"Github Error getting Access Token: {result}"
            logging.exception(message)
            response = {
                "message": message
            }
            return web.json_response(response, status=403)
        else:
            access_token = result['access_token']
            token_type = result['token_type']
            # then, will get user info:
            try:
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "X-OAuth-Scopes": "repo, user"
                }
                data = await self.get(self.userinfo_uri, token=access_token, token_type='token', headers=headers)
                if data:
                    userdata, uid = self.build_user_info(data)
                    # also, user information:
                    data = await self.get_user_session(request, uid, userdata, access_token)
                    # Redirect User to HOME
                    return self.home_redirect(request, token=data["token"], token_type='Bearer')
                else:
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
