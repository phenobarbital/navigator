from abc import ABC, ABCMeta, abstractmethod


class BaseAuthHandler(ABC):
    """Abstract Base for Authentication."""

    def configure(self):
        pass

    @abstractmethod
    async def check_credentials(self, request):
        pass
