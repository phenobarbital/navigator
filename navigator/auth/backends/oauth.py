"""Oauth.

Oauth is a Abstract Class with basic functionalities for all Oauth2 backends.
"""
from aiohttp import web
from .external import ExternalAuth
from navigator.exceptions import (
    NavException
)
from abc import abstractmethod
from typing import Dict


class OauthAuth(ExternalAuth):
    """OauthAuth.

    Description: Abstract Class for all Oauth2 backends.
    """
    _auth_code: str = 'code'

    @abstractmethod
    async def get_credentials(self, request: web.Request):
        pass

    async def authenticate(self, request: web.Request):
        """ Authenticate, refresh or return the user credentials."""
        try:
            domain_url = self.get_domain(request)
            self.redirect_uri = self.redirect_uri.format(domain=domain_url, service=self._service_name)
            # Build the URL
            params = await self.get_credentials(request)
            url = self.prepare_url(self.authorize_uri, params)
            # Step A: redirect
            return self.redirect(url)
        except Exception as err:
            raise NavException(
                f"{self._service_name}: Client doesn't have info for Authentication: {err}"
            ) from err

    def get_auth_response(self, request: web.Request) -> Dict:
        return dict(request.rel_url.query.items())

    def get_auth_code(self, response: Dict) -> str:
        try:
            code = response.get(self._auth_code)
        except KeyError:
            code = None
        if not code:
            raise RuntimeError(
                f"Auth Error: {self._service_name} Code not accessible"
            )
        return code
