""" Authorization based on HOSTS lists."""

from .base import BaseAuthzHandler
from navigator.conf import HOSTS
from aiohttp import web

class authz_hosts(BaseAuthzHandler):
    """
    BasicHosts.
       Use for basic Host authorization, simply creating a list of allowed hosts
    """

    async def check_authorization(self, request: web.Request) -> bool:
        print(HOST)
        if request.host in HOSTS:
            return True
        try:
            if request.headers["origin"] in HOSTS:
                return True
        except KeyError:
            return False
        return False
