"""Django Session Backend.

Navigator Authentication using Django Session Backend
"""
import logging
import asyncio
from aiohttp import web, hdrs
from .base import BaseAuthBackend
import uuid


class NoAuth(BaseAuthBackend):
    """Basic Handler for No authentication."""

    user_attribute: str = "userid"

    async def check_credentials(self, request):
        """ Authentication and create a session."""
        return True

    async def authenticate(self, request):
        return True

    async def get_session(self, request):
        return {}

    async def auth_middleware(self, app, handler):
        async def middleware(request):
            return await handler(request)

        return middleware
