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
        payload = {
            self.user_property: None,
            self.username_attribute: "Anonymous"
        }
        token = self.create_jwt(data=payload)
        return {
            "token": token,
            "id": uuid.uuid4().hex,
            "username": "Anonymous"
        }
