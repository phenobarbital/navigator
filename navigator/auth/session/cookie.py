"""Cookie-based Session Storage."""

from aiohttp_session.cookie_storage import EncryptedCookieStorage
from .base import AbstractSession
from aiohttp_session import setup as setup_session
from navigator.conf import DOMAIN, SESSION_TIMEOUT


class CookieSession(AbstractSession):
    """Encrypted Cookie Session Storage."""

    def configure_session(self, app):
        """Cookie Session Configuration."""
        print(self.secret_key, self.session_name)
        setup_session(
            app,
            EncryptedCookieStorage(
                self.secret_key,
                cookie_name=self.session_name,
                max_age=SESSION_TIMEOUT
                # domain=DOMAIN,
            ),
        )
