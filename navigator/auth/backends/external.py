"""ExternalAuth Backend.

Abstract Model to any Oauth2 or external Auth Support.
"""
import asyncio
from typing import (
    Dict,
    Any,
    Tuple,
    Callable
)
import importlib
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from abc import abstractmethod
import aiohttp
from aiohttp import web, hdrs
from aiohttp.client import (
    ClientTimeout,
    ClientSession
)
from navigator.auth.identities import AuthUser
from navigator.exceptions import UserNotFound
from navigator.conf import (
    AUTH_LOGIN_FAILED_URI,
    AUTH_REDIRECT_URI,
    AUTH_MISSING_ACCOUNT,
    AUTH_SUCCESSFUL_CALLBACKS
)
from navconfig.logging import logging
from requests.models import PreparedRequest
from urllib.parse import urlparse, parse_qs
from .base import BaseAuthBackend


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
    _user_mapping: Dict = {}
    _ident: AuthUser = OauthUser

    def __init__(
        self,
        user_attribute: str = None,
        userid_attribute: str = None,
        password_attribute: str = None,
        credentials_required: bool = False,
        authorization_backends: tuple = (),
        **kwargs,
    ):
        super().__init__(
            user_attribute,
            userid_attribute,
            password_attribute,
            credentials_required,
            authorization_backends,
            **kwargs
        )
        self.base_url: str = ''
        self.authorize_uri: str = ''
        self.userinfo_uri: str = ''
        self._token_uri: str = ''
        self.login_failed_uri = AUTH_LOGIN_FAILED_URI
        self.redirect_uri = "{domain}/auth/{service}/callback/"
        self._issuer: str = None
        self.users_info: str = None
        self.authority: str = None

    def configure(self, app, router, handler):
        # add the callback url
        router = app.router
        # TODO: know the host we already are running
        # start login
        router.add_route(
            "*",
            f"/api/v1/auth/{self._service_name}/",
            self.authenticate,
            name=f"{self._service_name}_api_login"
        )
        # finish login (callback)
        router.add_route(
            "GET",
            f"/auth/{self._service_name}/callback/",
            self.auth_callback,
            name=f"{self._service_name}_complete_login"
        )
        # logout process
        router.add_route(
            "GET",
            f"/api/v1/auth/{self._service_name}/logout",
            self.logout,
            name=f"{self._service_name}_api_logout"
        )
        router.add_route(
            "GET",
            f"/auth/{self._service_name}/logout",
            self.finish_logout,
            name=f"{self._service_name}_complete_logout"
        )
        super(ExternalAuth, self).configure(app, router, handler)

    def get_domain(self, request: web.Request) -> str:
        absolute_uri = str(request.url)
        domain_url = absolute_uri.replace(str(request.rel_url), '')
        logging.debug(f'DOMAIN: {domain_url}')
        return domain_url

    def redirect(self, uri: str):
        """redirect.
            Making the redirection to External Auth Page.
        """
        logging.debug(f'{self.__class__.__name__} URI: {uri}')
        return web.HTTPFound(uri)

    def prepare_url(self, url: str, params: Dict = None):
        req = PreparedRequest()
        req.prepare_url(url, params)
        return req.url

    def home_redirect(self, request: web.Request, token: str = None, token_type: str = 'Bearer'):
        domain_url = self.get_domain(request)
        if bool(urlparse(AUTH_REDIRECT_URI).netloc):
            # is an absolute URI
            redirect_url = AUTH_REDIRECT_URI
        else:
            redirect_url = f"{domain_url}{AUTH_REDIRECT_URI}"
        headers = {
            "x-authenticated": 'true'
        }
        params = {}
        if token:
            headers["x-auth-token"] = token
            headers["x-auth-token-type"] = token_type
            params = {
                "token" : token, "type":  token_type
            }
        url = self.prepare_url(redirect_url, params)
        return web.HTTPFound(url, headers=headers)

    @abstractmethod
    async def authenticate(self, request: web.Request):
        """ Authenticate, refresh or return the user credentials."""

    @abstractmethod
    async def auth_callback(self, request: web.Request):
        """auth_callback, Finish method for authentication."""

    @abstractmethod
    async def logout(self, request: web.Request):
        """logout, forgot credentials and remove the user session."""

    @abstractmethod
    async def finish_logout(self, request: web.Request):
        """finish_logout, Finish Logout Method."""

    def build_user_info(self, userdata: Dict) -> Tuple:
        """build_user_info.
            Get user or validate user from model.
        Args:
            userdata (Dict): User data gets from Auth Backend.

        Returns:
            Tuple: user_id and user_data.
        Raises:
            UserNotFound: when user doesn't exists on Backend.
        """
        # User ID:
        userid = userdata[self.userid_attribute]
        userdata['id'] = userid
        userdata[self.session_key_property] = userid
        userdata['auth_method'] = self._service_name
        for key, val in self._user_mapping.items():
            try:
                userdata[key] = userdata[val]
            except KeyError:
                pass
        return (userdata, userid)

    async def validate_user_info(
            self,
            request: web.Request,
            user_id: Any,
            userdata: Any,
            token: str
        ) -> Dict:
        data = None
        user = None
        # then, if everything is ok with user data, can we validate from model:
        try:
            login = userdata[self.username_attribute]
        except KeyError:
            login = userdata[self.user_attribute]
        try:
            search = {self.username_attribute: login}
            user = await self.get_user(**search)
        except UserNotFound as err:
            if AUTH_MISSING_ACCOUNT == 'ignore':
                pass
            elif AUTH_MISSING_ACCOUNT == 'raise':
                raise UserNotFound(
                    f"User {login} doesn't exists"
                ) from err
            elif AUTH_MISSING_ACCOUNT == 'create':
                # can create an user using userdata:
                pass
            else:
                raise RuntimeError(
                    f"Oauth2: Invalid config for AUTH_MISSING_ACCOUNT: {AUTH_MISSING_ACCOUNT}"
                ) from err
        if user:
            # construir e invocar callbacks para actualizar data de usuario
            for fn in AUTH_SUCCESSFUL_CALLBACKS:
                await self.auth_successful_callback(request, fn, userdata, user)
        try:
            user = await self.create_user(
                userdata
            )
            try:
                user.username = userdata[self.username_attribute]
            except KeyError:
                user.username = user_id
            user.token = token # issued token:
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

    def get(self, url, **kwargs) -> web.Response:
        """Perform an HTTP GET request."""
        return self.request(url, method=hdrs.METH_GET, **kwargs)

    def post(self, url, **kwargs) -> web.Response:
        """Perform an HTTP POST request."""
        return self.request(url, method=hdrs.METH_POST, **kwargs)

    async def request(
            self,
            url: str,
            method: str ='get',
            token: str = None,
            token_type: str = 'Bearer',
            **kwargs
        ) -> web.Response:
        """
        request.
            connect to an http source using aiohttp
        """
        timeout = ClientTimeout(total=120)
        if 'headers' in kwargs:
            headers = kwargs['headers'].copy()
            del kwargs['headers']
        else:
            headers = {}
        if token:
            headers["Authorization"] = f"{token_type} {token}"
        if 'content-type' not in headers:
            headers['content-type'] = 'application/json'
            headers['Accept'] = 'application/json'
        response = None
        async with ClientSession(trust_env=True) as client:
            async with client.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                **kwargs
            ) as response:
                logging.debug(f'{url} with response: {response.status}, {response!s}')
                if response.status == 200:
                    try:
                        return await response.json()
                    except aiohttp.client_exceptions.ContentTypeError:
                        resp = await response.read()
                        return parse_qs(resp.decode("utf-8"))
                else:
                    resp = await response.read()
                    raise Exception(f'Error getting Session Information: {resp}')

    async def auth_successful_callback(
            self,
            request: web.Request,
            fn: str,
            userdata: Dict,
            user: Callable,
        ) -> None:
        loop = asyncio.get_event_loop()
        try:
            func = partial(self.call_successful_callbacks, request, fn, user, userdata)
            with ThreadPoolExecutor(max_workers=10) as executor:
                loop.run_in_executor(executor, func, loop)
        except Exception as e:
            print(e)

    def call_successful_callbacks(
        self,
        request: web.Request,
        fn: str,
        user: Callable,
        userdata: Dict,
        loop: asyncio.AbstractEventLoop
        ) -> None:
        # start here:
        asyncio.set_event_loop(loop)
        print('Calling the Successful Callback')
        obj = None
        try:
            pkg, module = fn.rsplit('.', 1)
            mod = importlib.import_module(pkg)
            obj = getattr(mod, module)
            try:
                loop.run_until_complete(
                    obj(request, user, userdata)
                )
            except Exception as e:
                logging.exception(e, stack_info=False)
        except ImportError as e:
            raise RuntimeError(
                f"Auth Callback: Error importing Function: {fn}, {e!s}"
            ) from e
