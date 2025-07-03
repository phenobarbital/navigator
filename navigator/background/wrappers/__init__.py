from typing import Callable, Coroutine, Any, Union, Optional, Awaitable
import uuid
import logging
import threading
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from ..tracker import JobTracker, JobRecord


coroutine = Callable[[int], Coroutine[Any, Any, str]]
OnCompleteFn = Callable[[Any, Optional[Exception]], Awaitable[None]]


def coroutine_in_thread(
    coro: coroutine,
    callback: Optional[coroutine] = None,
    on_complete: OnCompleteFn = None,
) -> threading.Event:
    """Run a coroutine in a new thread with its own event loop."""
    parent_loop = asyncio.get_running_loop()
    done_event = threading.Event()

    def _runner():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        result, exc = None, None
        try:
            result = new_loop.run_until_complete(coro)
        except Exception as e:         # noqa: BLE001
            exc = e
        finally:
            if callback:
                new_loop.run_until_complete(
                    callback(result, exc, loop=new_loop)
                )
            new_loop.close()
            done_event.set()  # Signal that the coroutine has completed
            if on_complete is None:
                return
            fut = asyncio.run_coroutine_threadsafe(
                on_complete(result, exc), parent_loop
            )
            fut.result()  # Wait for the completion of the callback

    threading.Thread(target=_runner, daemon=True).start()
    return done_event


class TaskWrapper:
    """TaskWrapper.

    Task Wrapper for Background Task Execution.
    """
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        tracker: JobTracker = None,
        jitter: float = 0.0,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs
    ):
        self.fn = fn
        self.tracker = tracker
        self._name: str = kwargs.pop('name', fn.__name__ if fn else 'unknown_task')
        self._user_callback: Union[Callable, Awaitable] = kwargs.pop('callback', None)
        job_status = kwargs.pop('status', 'pending')
        if job_status not in ['pending', 'running', 'done', 'failed']:
            raise ValueError(
                f"Invalid job status '{job_status}'. "
                "Must be one of: 'pending', 'running', 'done', 'failed'."
            )
        self.jitter: float = jitter
        # Create the Job Record at status "pending"
        # generate a list of arguments accepted by JobRecord:
        content = kwargs.pop('content', None)
        job_args = {
            k: v for k, v in kwargs.items()
            if not k.startswith('_') and k in JobRecord.__fields__
        }
        self.job_record: JobRecord = JobRecord(
            name=self._name,
            content=content,
            status=job_status,
            **job_args
        )
        self.logger = logger or logging.getLogger(
            'NAV.Queue.TaskWrapper'
        )
        # Retry information:
        self.max_retries = max_retries
        self.retries_done = 0
        self.retry_delay = retry_delay
        # Store the arguments and keyword arguments for the Function
        self.args = args
        self.kwargs = kwargs

    @property
    def task_uuid(self) -> uuid.UUID:
        return self.job_record.task_id

    def __repr__(self):
        return f"<TaskWrapper function={self._name}>"

    def add_callback(self, callback: Union[Callable, Awaitable]):
        """add_callback.

        Description: Add a callback function to the TaskWrapper.

        Args:
        - callback (Union[Callable, Awaitable]):
            Callback function to be called after the task is executed.
        """
        self._user_callback = callback

    async def _wrapped_callback(self, result, exc, loop):
        """
        Internal wrapper callback that injects JobRecord information
        before calling the user's callback.

        Args:
        - result: The result of the task execution.
        - exc: Exception raised during task execution, if any.
        - loop: The event loop in which the task was executed.
        """
        if self._user_callback:
            # Call user callback with additional JobRecord info
            # New signature: callback(result, exc, loop, job_record, task_id)
            await self._user_callback(
                result,
                exc,
                loop=loop,
                job_record=self.job_record,
                task_id=self.job_record.task_id
            )

    async def __call__(self):
        result = None
        # tell tracker we’re starting
        try:
            if self.tracker:
                await self.tracker.set_running(self.task_uuid)
            self.logger.debug(
                f"executing {self._name}  with args: {self.args} and kwargs: {self.kwargs!r}"
            )
        except Exception as e:
            self.logger.error(
                f"Error setting task {self._name} as running: {e}"
            )
            return {
                "status": "failed",
                "error": e
            }
        if self.jitter > 0:
            # Random delay between 0 and jitter to avoid "thundering herd" problem
            delay = random.uniform(0.1, self.jitter)
            self.logger.debug(
                f"executing {self._name} with Jitter: {delay} sec."
            )
            # Delay the execution by jitter seconds
            await asyncio.sleep(delay)
        try:
            async def _finish(result: Any, exc: Exception):
                """Callback to handle the completion of the coroutine."""
                if exc:
                    self.logger.error(
                        f"TaskWrapper {self._name} failed with exception: {exc}"
                    )
                    result = {
                        "status": "failed",
                        "error": str(exc)
                    }
                    if self.tracker:
                        await self.tracker.set_failed(self.task_uuid, exc)
                else:
                    self.logger.debug(
                        f"TaskWrapper {self._name} completed successfully."
                    )
                    result = {
                        "status": "done",
                        "result": result
                    }
                    if self.tracker:
                        await self.tracker.set_done(self.task_uuid, result)
                return result
            with ThreadPoolExecutor(max_workers=1) as executor:
                coro = self.fn(*self.args, **self.kwargs)
                # Use the wrapped callback instead of the user callback directly
                callback_to_use = self._wrapped_callback if self._user_callback else None
                coroutine_in_thread(coro, callback_to_use, on_complete=_finish)
                return {"status": "running"}
        except asyncio.CancelledError:
            self.logger.warning(
                f"TaskWrapper {self.fn.__name__} was cancelled."
            )
            result = {
                "status": "cancelled"
            }
            if self.tracker:
                await self.tracker.set_failed(self.task_uuid, "Cancelled")
        except Exception as e:
            self.logger.error(
                f"Error executing TaskWrapper {self._name}: {e}"
            )
            result = {
                "status": "failed",
                "error": e
            }
        return result
