"""Routes.

Define Path Router configuration.
"""
from abc import ABC, abstractmethod
from ast import Dict
from typing import Any, List, Optional, Union
from aiohttp import web
from aiohttp.web import Request
from aiohttp.web_urldispatcher import URL
from aiohttp.web_exceptions import HTTPNotAcceptable
from .types import HTTPMethod, HTTPLocation, HTTPHandler


def add_resource(app: web.Application, resource: str, name: str) -> None:
    """add_resource.

    Description:
        Add a resource to the application.

    Args:
        app (web.Application): The application object.
        resource (str): The resource to add.
        name (str): The name of the resource.
    """  # noqa
    app.router.add_resource(resource, name=name)

def get_resource(
    request: Request,
    resource: str,
    args: dict,
    queryparams: Optional[Union[dict, str]] = None
) -> URL:
    """get_resource.

    Description:
        Get a resource from the request.

    Args:
        request (Request): The request object.
        resource (str): The resource to get.
        args (dict): The arguments to use.
        queryparams (Optional[dict], optional): The query parameters to use. Defaults to None.

    Returns:
        URL: The URL object.
    """  # noqa
    rq = request.app.router[resource].url_for(**args)
    if queryparams:
        rq = rq.with_query(queryparams)
    return rq


class path(object):
    """path.

    Description:
        Django-like URL router configuration
        Works exactly like Django's path method. It takes a URL pattern, a handler, and an optional name to create a new route in the application.

    Args:
        url (str): The URL pattern for the route.
        handler (callable): The handler function or class for the route.
        name (str, optional): The name of the route. Defaults to None.

    Returns:
        Route: The created route object.
    """  # noqa
    def __init__(
        self,
        method: HTTPMethod,
        url: HTTPLocation,
        handler: HTTPHandler,
        name: str = "",
    ) -> None:
        self.method = method
        self.url = url
        self.handler = handler
        self.name = name


def class_url(
    handler: HTTPHandler,
    route: str = None,
    prefix: Optional[str] = None,
) -> list:
    """
    Takes a class-based view as a handler, a route, and an optional prefix to build all routes required by a class-based view.

    Args:
        handler (HTTPHandler): The class-based view handler.
        route (str, optional): The base route for the handler. If not provided, the handler's `path` attribute will be used. Defaults to None.
        prefix (Optional[str], optional): An optional prefix to prepend to the route. Defaults to None.

    Returns:
        list: A list of routes built for the class-based view.

    Raises:
        Exception: If neither `route` nor the handler's `path` attribute is provided.
    """  # noqa
    if not route:
        try:
            route = handler.path
        except AttributeError:
            raise Exception(
                "Route or an Attribute *path* is required"
            )
    name = handler.__name__.lower()
    if not prefix:
        prefix = ""
    elif prefix.endswith("/"):
        prefix = prefix[:-1]
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
    url = f"{prefix}/{route}"
    return [
        path(
            "", r"{}".format(url),
            handler,
            name=f"{name}_{route}"
        ),
        path(
            "", r"{}/{{id:.*}}".format(url),
            handler,
            name=f"{name}_{route}_id"
        ),
        path(
            "",
            r"{}{{meta:\:?.*}}".format(url),
            handler,
            name=f"{name}_{route}_meta"
        ),
    ]


def class_urls(
    handlers: List[HTTPHandler],
    routes: list,
    prefix: Optional[str] = None,
) -> list:
    """
    Takes a class-based view as a handler, a list of routes, and an optional prefix to build all routes required by a class-based view.

    Args:
        handlers (list of HTTPHandler): The class-based view handler.
        routes (list): A list of routes for the handler.
        prefix (Optional[str], optional): An optional prefix to prepend to the route. Defaults to None.

    Returns:
        list: A list of routes built for the class-based view.

    Raises:
        Exception: If neither `route` nor the handler's `path` attribute is provided.
    """  # noqa
    if not handlers:
        raise Exception(
            "Handlers are required"
        )
    if not routes:
        raise Exception(
            "Routes are required"
        )
    r = []
    for idx, handler in enumerate(handlers):
        r.extend(class_url(handler, routes[idx], prefix))
    return r


class RouteChooser(ABC):
    """RouteChooser.

    Description:
        Abstract class for choosing a route based on the request.
    """
    def __init__(self) -> None:
        self._handlers_: Dict[HTTPHandler] = {}

    @abstractmethod
    async def choose(self, request: Request) -> Optional[HTTPHandler]:
        """choose.

        Description:
            Choose a route based on the request.

        Args:
            request (Request): The request object.

        Returns:
            Optional[Route]: The chosen route.
        """
        pass

    def add_handler(self, option: Any, handler: HTTPHandler) -> HTTPHandler:
        """add_handler.

        Description:
            Add a handler to the list of accessors based on the option.

        Args:
            option (Any): The option to use to choose the handler.
            handler (HTTPHandler): The handler to be selected.

        Returns:
            HTTPHandler: The defined handler.
        """
        self._handlers_[option] = handler
        return handler


class AcceptChooser(RouteChooser):
    """AcceptChooser.

    Description:
        RouteChooser that selects a handler based on the request's Accept header.
    """
    async def choose(self, request: Request) -> Optional[HTTPHandler]:
        """choose.

        Description:
            Choose a route based on the request's Accept header.

        Args:
            request (Request): The request object.

        Returns:
            Optional[Route]: The chosen route.
        """
        for accept in request.headers.getall('ACCEPT', []):
            if accept in self._handlers_:
                return (await self._handlers_[accept])
        raise HTTPNotAcceptable()
