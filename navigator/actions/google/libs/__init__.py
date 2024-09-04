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
