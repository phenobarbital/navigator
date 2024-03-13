from abc import ABC
from ..conf import GOOGLE_API_KEY

class GoogleService(ABC):
    def __init__(self, *args, **kwargs):
        self._key_ = kwargs.get('api_key', GOOGLE_API_KEY)
        if not self._key_:
            raise ValueError(
                "Google API Key is not present."
            )
