import asyncio

from aiohttp import web
from aiohttp_session import get_session

from navigator.conf import HOSTS


class auth_hosts(object):
    """
    BasicHosts.
       Use basic Host authorization, simply creating a list of allowed hosts
    """

    async def check_authorization(self, request: web.Request) -> bool:
        if request.host in HOSTS:
            return {"host": request.host, "user_id": request.host}
        try:
            if request.headers["origin"] in HOSTS:
                return {"host": request.headers["origin"], "user_id": request.host}
        except KeyError:
            return False
        return False


class auth_users(object):
    async def check_authorization(self, request: web.Request) -> bool:
        session = await get_session(request)
        if "user_id" not in session:
            return False
        return session


class auth_django(object):
    async def check_authorization(self, request: web.Request) -> bool:
        session = await get_session(request)
        if "user_id" not in session:
            return False
        return session
