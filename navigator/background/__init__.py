import sys
from typing import Union, Optional, Any
from collections.abc import Awaitable, Callable, Coroutine
import time
import uuid
import asyncio
import random
import threading
from importlib import import_module
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import psutil
from aiohttp import web
from navconfig.logging import logging
from navigator.conf import QUEUE_CALLBACK

if sys.version_info >= (3, 10):  # pragma: no cover
    from typing import ParamSpec
else:  # pragma: no cover
    from typing_extensions import ParamSpec  # noqa

P = ParamSpec("P")
coroutine = Callable[[int], Coroutine[Any, Any, str]]

SERVICE_NAME: str = 'service_queue'


def coroutine_in_thread(coro: coroutine, callback: Optional[coroutine] = None):
    """Run a coroutine in a new thread with its own event loop."""
    done_event = threading.Event()

    def run():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        result = new_loop.run_until_complete(coro)
        # if callback exists:
        if callback:
            new_loop.run_until_complete(callback(result))
        new_loop.close()
        done_event.set()  # Signal that the coroutine has completed
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return done_event


class TaskWrapper:
    """TaskWrapper.

    Task Wrapper for Background Task Execution.
    """
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        jitter: float = 0.0,
        **kwargs
    ):
        self.args = args
        self.kwargs = kwargs
        self.fn = fn
        self._callback_: Union[Callable, Awaitable] = kwargs.get('callback', None)
        self.jitter: float = jitter

    def __repr__(self):
        return f"<TaskWrapper function={self.fn.__name__}>"

    def add_callback(self, callback: Union[Callable, Awaitable]):
        """add_callback.

        Description: Add a callback function to the TaskWrapper.

        Args:
        - callback (Union[Callable, Awaitable]):
          Callback function to be called after the task is executed.
        """
        self._callback_ = callback

    async def __call__(self):
        result = None
        if self.jitter > 0:
            # Random delay between 0 and jitter to avoid "thundering herd" problem
            delay = random.uniform(0.1, self.jitter)
            self.logger.debug(
                f"executing {self.fn.__name__} with Jitter: {delay} sec."
            )
            # Delay the execution by jitter seconds
            await asyncio.sleep(delay)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                coro = self.fn(*self.args, **self.kwargs)
                coroutine_in_thread(coro, self._callback_)
                return True  # end this
        except Exception as e:
            logging.error(
                f"Error executing TaskWrapper {self.fn.__name__}: {e}"
            )
            result = {
                "status": "failed",
                "error": e
            }
        if callable(self._callback_):
            # calling the callback function
            if asyncio.iscoroutinefunction(self._callback_):
                await self._callback_(result, *self.args, **self.kwargs)
            else:
                loop = asyncio.get_running_loop()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    await loop.run_in_executor(
                        executor,
                        self._callback_,
                        result,
                        *self.args,
                        **self.kwargs
                    )
        return result


class BackgroundQueue:
    """BackgroundQueue.

    Asyncio Queue with for background processing.

    TODO:
    - Add Task Timeout
    - Add Task Retry
    - Added Wrapper Support
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
        if isinstance(app, web.Application):
            self.app = app  # register the app into the Extension
        else:
            self.app = app.get_app()  # Nav Application
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
        try:
            await self.queue.put(None)  # Send a termination signal to the queue
            await self.empty_queue()
        except asyncio.TimeoutError:
            pass
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
            try:
                c.cancel()
            except asyncio.CancelledError:
                pass

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
            # with ThreadPoolExecutor(max_workers=1) as executor:
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
            except Exception as e:  # Catch all exceptions
                print('ERROR > ', e)
                self.logger.error(
                    f"Error executing task {func.__name__}: {e}"
                )
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
                    print('LOG ERROR > ', e)
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
