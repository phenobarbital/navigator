""" Authorization based on Allowed HOSTS lists."""
import fnmatch
import logging
from .base import BaseAuthzHandler
from navigator.conf import ALLOWED_HOSTS
from aiohttp import web


class authz_allow_hosts(BaseAuthzHandler):
    """
    Allowed Hosts.
       Check if Origin is on the Allowed Hosts List.
    """

    async def check_authorization(self, request: web.Request) -> bool:
        origin = request.host if request.host else request.headers["origin"]
        for key in ALLOWED_HOSTS:
            # print(origin, ALLOWED_HOSTS, key, fnmatch.fnmatch(origin, key))
            if fnmatch.fnmatch(origin, key):
                return True
        return False
