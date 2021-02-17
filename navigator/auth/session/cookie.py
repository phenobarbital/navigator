"""Cookie-based Session Storage."""

from aiohttp_session.cookie_storage import EncryptedCookieStorage
from .base import AbstractSession
from navigator.conf import (
    DOMAIN,
    SESSION_TIMEOUT
)


class CookieSession(AbstractSession):
    """Encrypted Cookie Session Storage."""

    def configure(self):
        """Cookie Session Configuration."""
        self.session = EncryptedCookieStorage(
            self.secret_key,
            cookie_name=self.session_name,
            domain=DOMAIN,
            max_age=SESSION_TIMEOUT
        )
        return self.session
