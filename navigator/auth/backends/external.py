"""ExternalAuth Backend.

Abstract Model to any Oauth2 or external Auth Support.
"""
import logging
from aiohttp import web
from .base import BaseAuthBackend
from typing import (
    Dict,
    List,
    Any
)
from abc import abstractmethod
from navigator.conf import (
    AUTH_SESSION_OBJECT,
    AUTH_LOGIN_FAILED_URI,
    AUTH_REDIRECT_URI
)
from navigator.auth.identities import AuthUser
from typing import List

class OauthUser(AuthUser):
    token: str
    given_name: str
    family_name: str
    
    def __post_init__(self, data):
        super(OauthUser, self).__post_init__(data)
        self.first_name = self.given_name
        self.last_name = self.family_name

class ExternalAuth(BaseAuthBackend):
    """ExternalAuth.

    is an abstract base to any External Auth backend, as Oauth2 or OpenId.
    """
    user_attribute: str = "user"
    username_attribute: str = "username"
    pwd_atrribute: str = "password"
    _service_name: str = "service"


    def configure(self, app, router, handler):
        # add the callback url
        router = app.router
        self.base_url: str = ''
        self.authorize_uri: str = ''
        self.userinfo_uri: str = ''
        self._token_uri: str = ''
        # TODO: know the host we already are running
        self.login_failed_uri = AUTH_LOGIN_FAILED_URI
        self.redirect_uri = "http://localhost:5000/auth/{}/callback/".format(self._service_name)
        # start login
        router.add_route(
            "GET",
            "/api/v1/auth/{}/".format(self._service_name),
            self.authenticate,
            name="{}_api_login".format(self._service_name)
        )
        # finish login (callback)
        router.add_route(
            "GET",
            "/auth/{}/callback/".format(self._service_name),
            self.auth_callback,
            name="{}_complete_login".format(self._service_name)
        )
        # logout process
        router.add_route(
            "GET",
            "/api/v1/auth/{}/logout".format(self._service_name),
            self.logout,
            name="{}_api_logout".format(self._service_name)
        )
        router.add_route(
            "GET",
            "/auth/{}/logout".format(self._service_name),
            self.finish_logout,
            name="{}_complete_logout".format(self._service_name)
        )
        super(ExternalAuth, self).configure(app, router, handler)
 
    def redirect(self, uri: str):
        """redirect.
            Making the redirection to External Auth Page.
        """
        logging.debug(f'{self.__class__.__name__} URI: {uri}')
        return web.HTTPFound(uri)
    
    def home_redirect(self):
        logging.debug(f'Finish Auth URI::: {AUTH_REDIRECT_URI}')
        return web.HTTPFound(AUTH_REDIRECT_URI)

    @abstractmethod
    async def authenticate(self, request: web.Request):
        """ Authenticate, refresh or return the user credentials."""
        pass
    
    @abstractmethod
    async def auth_callback(self, request: web.Request):
        """auth_callback, Finish method for authentication."""
        pass
    
    @abstractmethod
    async def logout(self, request: web.Request):
        """logout, forgot credentials and remove the user session."""
        pass
    
    @abstractmethod
    async def finish_logout(self, request: web.Request):
        """finish_logout, Finish Logout Method."""
        pass
    
    async def create_user(self, request: web.Request, user_id: Any, userdata: Any, token: str):
        # TODO: only creates after validation:
        data = None
        try:
            user = OauthUser(data=userdata)
            user.id = user_id
            try:
                user.username = userdata[self.username_attribute]
            except KeyError:
                user.username = user_id
            user.token = token # issued token:
            logging.debug(f'User Created > {user}')
            payload = {
                "user_id": user_id,
                **userdata
            }
            # saving Auth data.
            await self.remember(
                request, user_id, userdata, user
            )
            # Create the User session.
            jwt_token = self.create_jwt(data=payload)
            data = {
                "token": jwt_token,
                "access_token": token,
                **userdata
            }
        except Exception as err:
            logging.exception(err)
        finally:
            return data
    
    @abstractmethod
    async def check_credentials(self, request: web.Request):
        """Check the validity of the current issued credentials."""
        pass