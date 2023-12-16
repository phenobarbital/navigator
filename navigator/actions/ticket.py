from abc import abstractmethod
from collections.abc import Callable
from .abstract import AbstractAction


class AbstractTicket(AbstractAction):
    """AbstractTicket.

    Managing Ticket system using Actions.
    """
    def __init__(self, *args, **kwargs):
        super(AbstractTicket, self).__init__(*args, **kwargs)
        self.service: Callable = None
        try:
            self._action_ = self._kwargs['action']
            del self._kwargs['action']
        except KeyError:
            self._action_ = 'create'

    @abstractmethod
    async def create(self, *args, **kwargs):
        """create.

        Create a new Ticket.
        """

    async def run(self, *args, **kwargs):
        if not self.service:
            await self.open()
        try:
            if self._action_ == 'create':
                params = {
                    **self._kwargs, **kwargs
                }
                return await self.create(*self._args, **params)
        except Exception as exc:
            self._logger.error(
                f"Error creating new Ticket: {exc}"
            )
            raise
