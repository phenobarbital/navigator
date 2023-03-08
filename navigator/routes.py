"""Routes.

Define Path Router configuration.
"""
from navigator.types import HTTPMethod, HTTPLocation, HTTPHandler


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
