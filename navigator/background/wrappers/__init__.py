from typing import Callable, Coroutine, Any, Union, Optional, Awaitable
import uuid
import logging
import threading
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from ..tracker import JobTracker, JobRecord


coroutine = Callable[[int], Coroutine[Any, Any, str]]


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
        tracker: JobTracker = None,
        jitter: float = 0.0,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs
    ):
        self.args = args
        self.kwargs = kwargs
        self._name: str = kwargs.get('name', fn.__name__ if fn else 'unknown_task')
        self.fn = fn
        self.tracker = tracker
        self._callback_: Union[Callable, Awaitable] = kwargs.get('callback', None)
        self.jitter: float = jitter
        # Create the Job Record at status "pending"
        self.job_record: JobRecord = None
        if self.tracker:
            self.job_record: JobRecord = asyncio.run(
                tracker.create_job(name=self._name)
            )
        if not self.job_record:
            # define an unique task_id if not provided
            self.job_record = JobRecord(
                task_id=str(uuid.uuid4().hex),
                name=self._name
            )
        self.logger = logger or logging.getLogger('NAV.Queue.TaskWrapper')
        # Retry information:
        self.max_retries = max_retries
        self.retries_done = 0
        self.retry_delay = retry_delay

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
        self._callback_ = callback

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
            with ThreadPoolExecutor(max_workers=1) as executor:
                coro = self.fn(*self.args, **self.kwargs)
                coroutine_in_thread(coro, self._callback_)
                result = {
                    "status": "done"
                }
                if self.tracker:
                    # Set the job as done in the tracker
                    await self.tracker.set_done(self.task_uuid, result)
                return result
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
