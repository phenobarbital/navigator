"""Routes.

Define Path Router configuration.
"""
from aiohttp.abc import AbstractMatchInfo
from aiohttp import web, web_urldispatcher
from navigator.types import (
    HTTPMethod,
    HTTPLocation,
    HTTPRequest,
    HTTPHandler
)


#######################
##
## PATH CONFIGURATION
##
#######################
class path(object):
    """path.
    description: django-like URL router configuration
    """
    def __init__(self, method: HTTPMethod, url: HTTPLocation, handler: HTTPHandler, name: str = "") -> None:
        self.method = method
        self.url = url
        self.handler = handler
        self.name = name


class Router(web.UrlDispatcher):
    """Router.
    Matching resolution of Routes.
    """
    async def resolve(self, request: HTTPRequest) -> AbstractMatchInfo:
        res = await super().resolve(request)
        if isinstance(res, web_urldispatcher.MatchInfoError):
            if res.http_exception.status == 404:
                url = str(request.rel_url)
                if '/authorize' in url:
                    authorization = {
                        "status": "Tenant Authorized",
                        "program": 'Navigator'
                    }
                    return web_urldispatcher.MatchInfoError(
                        web.HTTPAccepted(
                            reason=authorization,
                            content_type='application/json'
                        )
                    )
                else:
                    return web_urldispatcher.MatchInfoError(
                        web.HTTPNotFound()
                    )
        return res
