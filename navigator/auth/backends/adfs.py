"""ADFSAuth.

Description: Backend Authentication/Authorization using Okta Service.
"""
import rapidjson
import logging
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthBackend
from typing import List, Dict, Any
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
    ADFS_RESOURCE,
    ADFS_AUDIENCE,
    ADFS_ISSUER,
    USERNAME_CLAIM,
    GROUP_CLAIM,
)
from aiohttp_session import new_session

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

    def configure(self, app, router):
        async def _setup_adfs(app):
            pass
        asyncio.get_event_loop().run_until_complete(_setup_adfs(app))
        # executing parent configurations
        super(ADFSAuth, self).configure(app, router)

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
            user, pwd = await self.get_payload(request)
            print('USER', user, pwd)
        except Exception as err:
            print(err)

    async def finish_auth(self, request):
        pass
