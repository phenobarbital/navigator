"""Django Session Backend.

Navigator Authentication using Django Session Backend
"""
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthHandler


class NoAuth(BaseAuthHandler):
    """Basic Handler for No authentication."""
    _scheme: str = 'Bearer'

    async def check_credentials(self, request):
        return True

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            request.user = None
            authz = await self.authorization_backends(app, handler, request)
            if authz:
                return authz
            else:
                return await handler(request)
        return middleware
