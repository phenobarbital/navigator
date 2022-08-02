""" Authorization based on Allowed HOSTS lists."""
import fnmatch
import logging
from .abstract import BaseAuthzHandler
from navigator.conf import ALLOWED_HOSTS
from aiohttp import web


class authz_allow_hosts(BaseAuthzHandler):
    """
    Allowed Hosts.
       Check if Origin is on the Allowed Hosts List.
    """

    def check_authorization(self, request: web.Request) -> bool:
        origin = request.host if request.host else request.headers["origin"]
        for key in ALLOWED_HOSTS:
            if fnmatch.fnmatch(origin, key):
                logging.debug(
                    f'Authorization based on ALLOW HOST {key}'
                )
                return True
        return False
