"""
Abstract Class for Authorization Policies and decorators
"""
from aiohttp import web
from abc import ABC, abstractmethod

class AuthorizationPolicy(ABC):
    @abstractmethod
    async def permits(self, identity, permission, context=None):
        """Check user permissions.
        Return True if the identity is allowed the permission in the
        current context, else return False.
        """
        pass

    @abstractmethod
    async def is_authorized(self, identity):
        """Retrieve authorized user id.
        Return the user_id of the user identified by the identity
        or 'None' if no user exists related to the identity.
        """
        pass

class BaseAuthzHandler(ABC):
    """ Abstract handler for Authorization Middleware."""
    @abstractmethod
    def check_authorization(self, request: web.Request) -> bool:
        pass
