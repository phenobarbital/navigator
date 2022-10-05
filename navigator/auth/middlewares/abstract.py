"""
Abstract Class for Navigator Authorization Middlewares.
"""
from typing import (
    Optional
)
from collections.abc import Callable, Awaitable
from abc import ABC, abstractmethod
import fnmatch
from aiohttp import web, hdrs
from aiohttp.web_urldispatcher import SystemRoute
from navigator_session import (
    SESSION_USER_PROPERTY
)


class base_middleware(ABC):

    anonymous_routes: list = ["/login", "logout", "/static/", "/signin", "/signout", "/_debugtoolbar/"]
    check_static: bool = True
    exclude_routes: tuple = tuple()
    protected_routes: tuple = tuple() # list of paths to be protected by middleware
    user_property: str = SESSION_USER_PROPERTY

    def __call__(
            self,
            request: web.Request,
            handler: Callable[[web.Request], Awaitable[web.Response]]
        ):
        """
        Base middleware returns a Awaitable Middleware.
        """
        return self.middleware(request, handler)

    def static_routes(self, request: web.Request):
        """
        Routes declares Statics.
        """
        for r in self.anonymous_routes:
            if request.path.startswith(r):
                return True
        return False

    def excluding_routes(self, request: web.Request):
        for path in self.exclude_routes:
            if fnmatch.fnmatch(request.path, path):
                return True
        return False

    def path_protected(self, request: web.Request):
        if request.path in self.protected_routes:
            return True
        return False


    async def valid_routes(self, request):
        """
        Avoid Authorization on System Routes.
        """
        request.user = None
        if isinstance(request.match_info.route, SystemRoute):  # eg. 404
            return True
        # avoid authorization on exclude list
        if self.exclude_routes and self.excluding_routes(request):
            return True
        if self.check_static is True:
            return self.static_routes(request)
        if request.method == hdrs.METH_OPTIONS:
            return True
        return False

    def get_authorization_header(
            self,
            request: web.Request,
            scheme: Optional[str] = None
        ):
        """
        Get the token and authorization header scheme.
        """
        _scheme = None
        token = None
        if 'Authorization' in request.headers:
            try:
                _scheme, token = request.headers['Authorization'].strip().split(' ')
            except KeyError as ex:
                raise web.HTTPUnauthorized(
                    reason='Token Auth: Missing authorization header',
                ) from ex
            except ValueError as ex:
                raise web.HTTPForbidden(
                    reason='Token Auth: Invalid authorization header',
            ) from ex
            if scheme is not None and scheme != _scheme:
                raise web.HTTPUnauthorized(
                    reason="Invalid Authorization Scheme"
                )
        else:
            try:
                token = request.query.get("auth", request.headers.get("X-Token", None))
            except KeyError:
                token = None
        return [token, _scheme]

    @abstractmethod
    async def middleware(
            self,
            app: web.Application,
            handler: Callable[[web.Request], Awaitable[web.Response]]
        ):
        """
        Abstract Method for declaring Middleware Function.
        """
