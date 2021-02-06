from abc import ABC, ABCMeta, abstractmethod


class BaseAuthHandler(ABC):
    """Abstract Base for Authentication."""


    @abstractmethod
    async def check_credentials(self, request):
        pass
