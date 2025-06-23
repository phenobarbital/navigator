import random
from typing import (
    Union,
    Optional,
    Any,
)
import sys
import uuid
from collections.abc import Awaitable, Callable, Coroutine
import contextlib
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import asyncio
import time
import psutil
from aiohttp import web
from navconfig.logging import logging
from ...conf import QUEUE_CALLBACK
from ..wrappers import TaskWrapper, coroutine_in_thread


if sys.version_info >= (3, 10):  # pragma: no cover
    from typing import ParamSpec
else:  # pragma: no cover
    from typing_extensions import ParamSpec  # noqa


coroutine = Callable[[int], Coroutine[Any, Any, str]]
P = ParamSpec("P")

SERVICE_NAME: str = 'service_queue'


class BackgroundQueue:
    """BackgroundQueue.

    Asyncio Queue with for background processing.

    TODO:
    - Add Task Timeout
    - Add Task Retry (done)
    - Added Wrapper Support (done)
    """
    service_name: str = SERVICE_NAME

    def __init__(
        self,
        app: Optional[web.Application],
        max_workers: int = 5,
        coro_in_threads: bool = True,
        **kwargs: P.kwargs
    ) -> None:
        self.logger = logging.getLogger('NAV.Queue')
        self.app = app if isinstance(app, web.Application) else app.get_app()
        self.max_workers = max_workers
        self.queue_size = kwargs.get('queue_size', 5)
        self._enable_profiling: bool = kwargs.get('enable_profiling', False)
        self.coro_in_threads: bool = coro_in_threads
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
        # Main Executor:
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers
        )

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
        # finish the threads:
        with contextlib.suppress(asyncio.TimeoutError):
            await self.queue.put(None)  # Send a termination signal to the queue
            await self.empty_queue()
        # also, finish the executor:
        self.shutdown_executor()
        self.logger.info(
            'Background Queue Processor Stopped.'
        )

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
            if isinstance(fn, (TaskWrapper, partial)):
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

    async def empty_queue(self, timeout: float = 5.0):
        """Processing and shutting down the Queue."""
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()

        try:
            await asyncio.wait_for(self.queue.join(), timeout)
        except asyncio.TimeoutError:
            self.logger.warning("Queue join timed out. Forcing shutdown.")

        # also: cancel the idle consumers:
        for _ in self.consumers:
            await self.queue.put(None)
        # Wait for all consumers to finish processing
        for c in self.consumers:
            with contextlib.suppress(asyncio.CancelledError):
                c.cancel()

    # Task Execution:
    async def _execute_taskwrapper(self, task: TaskWrapper):
        """Execute the a task as a TaskWrapper."""
        result = None
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                result = await task()
            except Exception as e:
                self.logger.exception(
                    f"Error executing TaskWrapper {task!r}: {e}",
                    exc_info=True
                )
                result = {
                    "status": "failed",
                    "error": e
                }
        return result

    async def _execute_coroutine(self, coro: coroutine):
        """Execute a coroutine."""
        result = None
        if self.coro_in_threads is True:
            coroutine_in_thread(coro)
            result = {
                "status": "queued"
            }
        else:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    asyncio.run,
                    coro
                )
            except Exception as e:
                self.logger.exception(
                    f"Error executing coroutine: {e}",
                    exc_info=True
                )
        return result

    async def _execute_callable(self, func: Callable, *args, **kwargs):
        """Execute a synchronous callable."""
        result = None
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self.executor,
                func,
                *args,
                **kwargs
            )
        except Exception as e:
            self.logger.exception(
                f"Error executing callable: {e}",
                exc_info=True
            )
            result = {
                "status": "error",
                "error": e
            }
        return result

    async def process_queue(self):
        """Process the Queue."""
        loop = asyncio.get_running_loop()
        while True:
            task = await self.queue.get()
            task_start_time = int(time.time() * 1000)
            initial_memory = 0
            peak_memory = 0
            if task is None:
                break  # Exit signal
            try:
                if self._enable_profiling is True:
                    # Resource Tracking Initialization
                    initial_memory = psutil.Process().memory_info().rss
                    peak_memory = initial_memory
            except Exception as e:
                self.logger.error(f"Error in Resource Tracking: {e}")

            self.logger.info(
                f":: Task started: {task!r}"
            )
            result = None
            try:
                if isinstance(task, TaskWrapper):
                    result = await self._execute_taskwrapper(task)
                elif isinstance(task, partial):
                    result = await self._execute_callable(task)
                else:
                    # Unpack the function and its arguments
                    func, args, kwargs = task
                    if asyncio.iscoroutinefunction(func):
                        coro = func(*args, **kwargs)
                        result = await self._execute_coroutine(coro)
                    elif callable(func):
                        result = await self._execute_callable(
                            func,
                            *args,
                            **kwargs
                        )
                    else:
                        self.logger.error(
                            f"Invalid Function {func} in Queue"
                        )
                        continue
            except Exception as exc:  # Catch all exceptions
                await self._handle_failure(task, exc)
                continue
            finally:
                if self._enable_profiling is True:
                    # Resource Tracking Finalization
                    memory_info = psutil.Process().memory_info()
                    peak_memory = max(peak_memory, memory_info.rss)
                else:
                    peak_memory = 0
                # Resource Tracking Finalization and Logging
                task_end_time = int(time.time() * 1000)
                task_duration = task_end_time - task_start_time
                try:
                    self.logger.info(f"""
                        Task completed: {task!r}
                        Duration: {task_duration:.2f} seconds
                        Initial Memory: {initial_memory / (1024 ** 2):.2f}
                        Peak Memory Usage: {peak_memory / (1024 ** 2):.2f} MB
                    """)
                except Exception as e:
                    print('TASK LOG ERROR > ', e)
                # Call your task completion callback (if any)
                try:
                    await self._callback(task, result=result)
                except Exception as e:
                    self.logger.error(
                        f"Error in Task Callback {self._callback}: {e}"
                    )
                # Signal task completion for the queue
                try:
                    self.queue.task_done()
                except Exception as e:
                    print(e)

    def shutdown_executor(self):
        self.executor.shutdown(wait=True)

    async def fire_consumers(self):
        """Fire up the Task consumers."""
        for _ in range(self.max_workers - 1):
            task = asyncio.create_task(
                self.process_queue()
            )
            self.consumers.append(task)

    async def _requeue(self, task: TaskWrapper, exc: Exception) -> None:
        """Internal: re-enqueues `task` after updating retry-counters."""
        task.retries_done += 1
        # optional exponential back-off
        if task.retry_delay:
            await asyncio.sleep(
                random.uniform(0.8, 1.2) * task.retry_delay * task.retries_done
            )

        self.logger.warning(
            f"Retry {task.retries_done}/{task.max_retries} for {task!r} "
            f"after error: {exc}"
        )
        if hasattr(task, "tracker"):
            # set status = "retrying"
            await task.tracker.set_running(task.task_uuid)
        await self.queue.put(task)

    async def _handle_failure(
        self,
        task: Any,
        exc: Exception
    ) -> None:
        """Central place that decides whether we retry or finally give up."""
        if (
            isinstance(task, TaskWrapper) and task.retries_done < task.max_retries
        ):
            await self._requeue(task, exc)
        else:
            self.logger.error(
                f"Task {task!r} failed permanently after "
                f"{getattr(task, 'retries_done', 0)} attempt(s)."
            )
            await self._callback(task, result=dict(status="failed", error=exc))


class BackgroundTask:
    """BackgroundTask.

    Calling blocking functions in the background.
    """
    def __init__(
        self,
        fn: Callable[P, Awaitable],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        self.fn = fn
        self.id = kwargs.pop('id', uuid.uuid4())
        self.in_thread = kwargs.pop('in_thread', False)
        self.args = args
        self.kwargs = kwargs

    async def __call__(self):
        return await self.fn(*self.args, **self.kwargs)

    def __repr__(self):
        return f'<BackgroundTask {self.fn.__name__} with ID {self.id}>'

    async def run(self):
        # TODO: add Callback to task wrapper.
        loop = asyncio.get_running_loop()
        if isinstance(self.fn, TaskWrapper):
            await self.fn()
        if isinstance(self.fn, partial):
            with ThreadPoolExecutor(max_workers=1) as executor:
                await loop.run_in_executor(executor, self.fn)
        elif asyncio.iscoroutinefunction(self.fn):
            coro = self.fn(*self.args, **self.kwargs)
            if self.in_thread is True:
                coroutine_in_thread(coro)
            else:
                await coro
        elif callable(self.fn):
            with ThreadPoolExecutor(max_workers=1) as executor:
                await loop.run_in_executor(
                    executor, self.fn, *self.args, **self.kwargs
                )
