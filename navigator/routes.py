"""Routes.

Define Path Router configuration.
"""
from typing import Optional
from .types import HTTPMethod, HTTPLocation, HTTPHandler


#######################
##
## PATH CONFIGURATION
##
#######################
class path(object):
    """path.
    description: django-like URL router configuration
    """

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
