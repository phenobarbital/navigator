from abc import ABC
from navconfig.logging import logging
from ..conf import GOOGLE_API_KEY

class GoogleService(ABC):
    def __init__(self, *args, **kwargs):
        self._key_ = kwargs.get('api_key', GOOGLE_API_KEY)
        self._logger = logging.getLogger(self.__class__.__name__)
        if not self._key_:
            raise ValueError(
                "Google API Key is not present."
            )

    async def __aenter__(self):
        self._logger.debug(f"Initializing {self.__class__.__name__} with API Key.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._logger.debug(f"Exiting {self.__class__.__name__}.")
        if exc_type:
            self._logger.error(f"An error occurred: {exc_val}")
        return False
