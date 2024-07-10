import sys
from typing import Union, Optional, Any
from collections.abc import Awaitable, Callable
if sys.version_info >= (3, 10):  # pragma: no cover
    from typing import ParamSpec
else:  # pragma: no cover
    from typing_extensions import ParamSpec

from importlib import import_module
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import asyncio
from aiohttp import web
from navconfig.logging import logging
from navigator.conf import QUEUE_CALLBACK


P = ParamSpec("P")

SERVICE_NAME: str = 'service_queue'


class BackgroundQueue:
    """BackgroundQueue.

    Asyncio Queue with for background processing.

    TODO:
    - Add Task Timeout
    - Add Task Retry
    - Adding Wrapper Support
    """
    service_name: str = SERVICE_NAME

    def __init__(self, max_workers: int = 5, **kwargs: P.kwargs) -> None:
        self.logger = logging.getLogger('NAV.Queue')
        self.max_workers = max_workers
        self.queue_size = kwargs.get('queue_size', 10)
        self.queue = asyncio.Queue(
            maxsize=self.queue_size
        )
        self.consumers: list = []
        self.logger.notice(
            f'Started Queue Manager with size: {self.queue_size}'
        )
        ### Getting Queue Callback (called when queue object is consumed)
        self._callback: Union[Callable, Awaitable] = self.get_callback(
            QUEUE_CALLBACK
        )
        self.logger.notice(
            f'Callback Queue: {self._callback!r}'
        )
        self.service_name: str = kwargs.get('service_name', SERVICE_NAME)

    def setup(self, app: Optional[web.Application]) -> None:
        if isinstance(app, web.Application):
            self.app = app  # register the app into the Extension
        else:
            self.app = app.get_app()  # Nav Application
        # Add Manager to main Application:
        self.app[self.service_name] = self
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_cleanup)

    async def on_cleanup(self, app: web.Application) -> None:
        """Application On cleanup."""
        await self.empty_queue()
        self.logger.info('Background Queue Processor Stopped.')

    async def on_startup(self, app: web.Application) -> None:
        """Application On startup."""
        await self.fire_consumers()
        self.logger.info('Background Queue Processor Started.')

    async def put(
        self,
        fn: Callable[P, Awaitable],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> None:
        try:
            if isinstance(fn, partial):
                await self.queue.put(fn)
            elif callable(fn):
                task = (fn, args, kwargs)
                await self.queue.put(task)
            else:
                self.queue.put_nowait(task)
            await asyncio.sleep(.1)
            return True
        except asyncio.queues.QueueFull:
            self.logger.error(
                f"Task Queue is Full, discarding Task {fn!r}"
            )
            raise

    async def task_callback(self, task: Any, **kwargs: P.kwargs):
        self.logger.info(
            f'Task Consumed: {task!r} with ID {task.id}'
        )

    def get_callback(self, done_callback: str) -> Union[Callable, Awaitable]:
        if not done_callback:
            ## returns a simple logger:
            return self.task_callback
        try:
            parts = done_callback.split(".")
            bkname = parts.pop()
            classpath = ".".join(parts)
            module = import_module(classpath, package=bkname)
            return getattr(module, bkname)
        except ImportError as ex:
            raise RuntimeError(
                f"Error loading Queue Callback {done_callback}: {ex}"
            ) from ex

    async def empty_queue(self):
        """Processing and shutting down the Queue."""
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        await self.queue.join()
        # also: cancel the idle consumers:
        for c in self.consumers:
            try:
                c.cancel()
            except asyncio.CancelledError:
                pass

    async def process_queue(self):
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        while True:
            task = await self.queue.get()
            if task is None:
                break  # Exit signal
            self.logger.info(
                f"Task started {task}"
            )
            result = None
            try:
                if isinstance(task, partial):
                    result = await loop.run_in_executor(executor, task)
                else:
                    # Unpack the function and its arguments
                    func, args, kwargs = task
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    elif callable(func):
                        result = await loop.run_in_executor(
                            executor, func, *args, **kwargs
                        )
            finally:
                ### Task Completed
                self.queue.task_done()
                await self._callback(
                    task, result=result
                )

    async def fire_consumers(self):
        """Fire up the Task consumers."""
        for _ in range(self.max_workers - 1):
            task = asyncio.create_task(
                self.process_queue()
            )
            self.consumers.append(task)
