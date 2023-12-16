from navconfig.logging import logging
from abc import ABC, abstractmethod

class AbstractAction(ABC):
    """AbstractAction.

    an Action is a pluggable component that can be used to perform operations.
    """
    def __init__(self, *args, **kwargs):
        self._name_ = self.__class__.__name__
        # log
        self._logger = logging.getLogger(self._name_)
        # program
        self._program = kwargs.pop('program', 'navigator')
        # attributes (root-level of component arguments):
        try:
            self._attributes = kwargs['attributes']
            del kwargs['attributes']
        except KeyError:
            self._attributes = {}
        try:
            self._arguments = kwargs['arguments']
            del kwargs['arguments']
        except KeyError:
            self._arguments = {}
        # Arguments of actions::
        try:
            self._arguments = {**kwargs, **self._arguments}
        except (TypeError, ValueError):
            pass
        # set the attributes of Action:
        for arg, val in self._arguments.items():
            if arg in self._attributes:
                val = self._attributes[arg]
            try:
                setattr(self, arg, val)
            except Exception as err:
                self._logger.warning(
                    f'Wrong Attribute: {arg}={val}'
                )
                self._logger.error(err)
        # You can define any initialization logic here, such as
        # storing parameters that control the behavior of the action.
        self._args = args
        self._kwargs = kwargs

    def __repr__(self):
        return f'<Action.{self._name_}>'

    @abstractmethod
    async def open(self):
        pass

    @abstractmethod
    async def close(self):
        pass

    @abstractmethod
    async def run(self, *args, **kwargs):
        # This is where you define the behavior of the action.
        # Since this method is asynchronous, you can use the "await"
        # keyword to call other asynchronous functions or coroutines.
        pass

    async def __aenter__(self) -> "AbstractAction":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # clean up anything you need to clean up
        return await self.close()
