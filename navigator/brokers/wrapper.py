"""
Abstract Wrapper Base.

Any other wrapper extends this.
"""
import random
import uuid


class BaseWrapper:
    _queued: bool = True
    _debug: bool = False

    def __init__(self, coro=None, *args, **kwargs):
        if 'queued' in kwargs:
            self._queued = kwargs['queued']
            del kwargs['queued']
        self._id = uuid.uuid1(
            node=random.getrandbits(48) | 0x010000000000
        )
        self.args = args
        self.kwargs = kwargs
        self.loop = None
        ## retry functionality
        self.retries = 0
        # function to be handled:
        self.coro = coro

    async def call(self):
        # Call the async function stored in the args[0] with *args[1:] and **kwargs
        await self.coro(*self.args[1:], **self.kwargs)

    async def __call__(self):
        return await self.coro(
            *self.args, **self.kwargs
        )

    def add_retries(self):
        self.retries += 1

    @property
    def queued(self):
        return self._queued

    @queued.setter
    def queued(self, value):
        self._queued = value

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, debug: bool = False):
        self._debug = debug

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        self._id = value

    def set_loop(self, event_loop):
        self.loop = event_loop
