from abc import ABC, ABCMeta, abstractmethod
from aiohttp import web, hdrs

class BaseAuthHandler(ABC):
    """Abstract Base for Authentication."""
    credentials_required: bool = False
    user_property: str = 'user'
    _scheme: str = 'Bearer'

    def __init__(self, credentials_required: bool = False, **kwargs):
        self.credentials_required = credentials_required
        self.user_property = kwargs['user_property']
        self._scheme = kwargs['scheme']

    def configure(self):
        pass

    async def authorization_backends(self, app, handler, request):
        if request.method == hdrs.METH_OPTIONS:
            return await handler(request)
        # logic for authorization backends
        return None

    @abstractmethod
    async def check_credentials(self, request):
        pass

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            return await handler(request)
        return middleware
