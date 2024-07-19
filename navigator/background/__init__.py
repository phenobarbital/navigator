import sys
from typing import Union, Optional, Any
from collections.abc import Awaitable, Callable
import uuid
if sys.version_info >= (3, 10):  # pragma: no cover
    from typing import ParamSpec
else:  # pragma: no cover
    from typing_extensions import ParamSpec
import psutil
import threading
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

    def __init__(
        self,
        app: Optional[web.Application],
        max_workers: int = 5,
        **kwargs: P.kwargs
    ) -> None:
        self.logger = logging.getLogger('NAV.Queue')
        if isinstance(app, web.Application):
            self.app = app  # register the app into the Extension
        else:
            self.app = app.get_app()  # Nav Application
        self.max_workers = max_workers
        self.queue_size = kwargs.get('queue_size', 5)
        self._enable_profiling: bool = kwargs.get('enable_profiling', False)
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
        ## Register the Queue Manager to the Application
        # Add Manager to main Application:
        self.app[self.service_name] = self
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_cleanup)
        # resource usage:
        self.peak_memory_usage = 0
        self.average_num_threads = 0
        self.cpu_usage = []

    async def get_resource_metrics(self):
        process = psutil.Process()
        memory_info = process.memory_info()
        return {
            "memory_rss": memory_info.rss,
            "memory_vms": memory_info.vms,
            "num_threads": process.num_threads(),
            "cpu_percent": process.cpu_percent()
        }

    async def on_cleanup(self, app: web.Application) -> None:
        """Application On cleanup."""
        await self.queue.put(None)  # Send a termination signal to the queue
        await self.empty_queue()
        self.logger.info('Background Queue Processor Stopped.')

    async def on_startup(self, app: web.Application) -> None:
        """Application On startup."""
        await self.fire_consumers()
        self.logger.info('Background Queue Processor Started.')

    async def put(
        self,
        fn: Union[partial, Callable[P, Awaitable], Any],
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
        self.logger.notice(
            f':: Task Executed: {task!r}'
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
        while True:
            task = await self.queue.get()
            task_start_time = asyncio.get_running_loop().time()
            if task is None:
                break  # Exit signal

            if self._enable_profiling is True:
                # Resource Tracking Initialization
                initial_memory = psutil.Process().memory_info().rss
                peak_memory = initial_memory

            self.logger.info(
                ":: Task started"
            )
            result = None
            try:
                try:
                    if isinstance(task, partial):
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            result = await loop.run_in_executor(executor, task)
                    else:
                        # Unpack the function and its arguments
                        func, args, kwargs = task
                        if asyncio.iscoroutinefunction(func):
                            result = await func(*args, **kwargs)
                        elif callable(func):
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                result = await loop.run_in_executor(
                                    executor, func, *args, **kwargs
                                )
                        else:
                            self.logger.error(
                                f"Invalid Function {func} in Queue"
                            )
                            continue
                except Exception as e:  # Catch all exceptions
                    self.logger.error(f"Error executing task {func.__name__}: {e}")
                    continue
                finally:
                    if self._enable_profiling is True:
                        # Resource Tracking Finalization
                        memory_info = psutil.Process().memory_info()
                        peak_memory = max(peak_memory, memory_info.rss)
            finally:
                if self._enable_profiling is True:
                    # Resource Tracking Finalization and Logging
                    task_end_time = asyncio.get_running_loop().time()
                    task_duration = task_end_time - task_start_time

                    self.logger.info(f"""
                        Task completed: {task!r}
                        Duration: {task_duration:.2f} seconds
                        Initial Memory: {initial_memory / (1024 ** 2):.2f}
                        Peak Memory Usage: {peak_memory / (1024 ** 2):.2f} MB
                    """)

                # Call your task completion callback (if any)
                try:
                    await self._callback(task, result=result)
                except Exception as e:
                    self.logger.error(
                        f"Error in Task Callback {self._callback}: {e}"
                    )
                # Signal task completion for the queue
                self.queue.task_done()

    async def fire_consumers(self):
        """Fire up the Task consumers."""
        for _ in range(self.max_workers - 1):
            task = asyncio.create_task(
                self.process_queue()
            )
            self.consumers.append(task)


class BackgroundTask:
    """BackgroundTask.

    Calling functions in the background.
    """
    def __init__(self, fn: Callable[P, Awaitable], *args: P.args, **kwargs: P.kwargs) -> None:
        self.fn = fn
        self.id = kwargs.pop('id', uuid.uuid4())
        self.args = args
        self.kwargs = kwargs

    async def __call__(self):
        return await self.fn(*self.args, **self.kwargs)

    def __repr__(self):
        return f'<BackgroundTask {self.fn.__name__} with ID {self.id}>'

    async def run(self):
        loop = asyncio.get_running_loop()
        if isinstance(self.fn, partial):
            with ThreadPoolExecutor(max_workers=1) as executor:
                await loop.run_in_executor(executor, self.fn)
        elif asyncio.iscoroutinefunction(self.fn):
            await self.fn(*self.args, **self.kwargs)
        elif callable(self.fn):
            with ThreadPoolExecutor(max_workers=1) as executor:
                await loop.run_in_executor(
                    executor, self.fn, *self.args, **self.kwargs
                )
