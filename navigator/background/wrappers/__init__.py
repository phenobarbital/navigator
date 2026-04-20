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

VALID_EXECUTION_MODES = ("same_loop", "thread", "remote")


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

    Args:
        fn: The callable or coroutine to execute.
        *args: Positional arguments to pass to fn.
        execution_mode: How to execute the task. One of:
            - ``"same_loop"`` (default): schedule on the running event loop
              via ``asyncio.create_task()``.
            - ``"thread"``: run in a dedicated thread with its own event loop
              via ``coroutine_in_thread()``.
            - ``"remote"``: dispatch to a remote qworker pool via
              :class:`~navigator.background.taskers.qworker.QWorkerTasker`.
        tracker: Optional JobTracker to update status.
        jitter: Maximum jitter delay in seconds before execution.
        logger: Optional logger instance.
        max_retries: Maximum number of retries on failure.
        retry_delay: Base delay between retries in seconds.
        remote_mode: Only used when ``execution_mode == "remote"``. One of
            ``"run"`` (wait for result), ``"queue"`` (fire-and-forget via
            TCP), or ``"publish"`` (fire-and-forget via Redis Streams).
        worker_list: Only used when ``execution_mode == "remote"``. Optional
            list of ``(host, port)`` tuples identifying the qworker pool.
        remote_timeout: Only used when ``execution_mode == "remote"``. TCP
            timeout (seconds) passed to ``QClient``.
        **kwargs: Additional keyword arguments passed to fn.
    """
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        execution_mode: str = "same_loop",
        tracker: JobTracker = None,
        jitter: float = 0.0,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs
    ):
        if execution_mode not in VALID_EXECUTION_MODES:
            raise ValueError(
                f"Invalid execution_mode '{execution_mode}'. "
                f"Must be one of: {VALID_EXECUTION_MODES!r}."
            )
        self.execution_mode = execution_mode
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
        # Remote execution params (only used when execution_mode == "remote").
        # Popped BEFORE building job_args so they are not leaked into the
        # JobRecord or forwarded to fn().
        self.remote_mode: str = kwargs.pop('remote_mode', 'run')
        self.worker_list = kwargs.pop('worker_list', None)
        self.remote_timeout: int = kwargs.pop('remote_timeout', 5)
        self._tasker = None  # lazy-created QWorkerTasker (see __call__)
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
        """Return the unique task identifier."""
        return self.job_record.task_id

    def __repr__(self):
        return f"<TaskWrapper function={self._name} mode={self.execution_mode}>"

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
        """Execute the wrapped function.

        If execution_mode == "same_loop": creates an asyncio.Task on the
        running loop, awaits it, and returns the result directly.

        If execution_mode == "remote": dispatches to a remote qworker pool
        via :class:`QWorkerTasker`. For ``remote_mode="run"`` it waits for
        and returns the remote result; for ``queue`` / ``publish`` it
        returns the QClient acknowledgement immediately.

        If execution_mode == "thread": delegates to coroutine_in_thread()
        (existing fire-and-forget behavior), returns {"status": "running"}.

        Returns:
            dict with "status" key: "done", "queued_remote", "failed",
            "cancelled", or "running".
        """
        result = None
        # Tell tracker we're starting
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
            await asyncio.sleep(delay)

        if self.execution_mode == "same_loop":
            # Schedule coroutine on the running event loop so all application-
            # scoped asyncio objects (sessions, locks, pools) work correctly.
            try:
                coro = self.fn(*self.args, **self.kwargs)
                result_val = await asyncio.create_task(coro)
                self.logger.debug(
                    f"TaskWrapper {self._name} completed successfully."
                )
                if self._user_callback:
                    await self._wrapped_callback(
                        result_val, None, loop=asyncio.get_running_loop()
                    )
                if self.tracker:
                    await self.tracker.set_done(self.task_uuid, result_val)
                return {"status": "done", "result": result_val}
            except asyncio.CancelledError:
                self.logger.warning(
                    f"TaskWrapper {self._name} was cancelled."
                )
                if self.tracker:
                    await self.tracker.set_failed(self.task_uuid, "Cancelled")
                return {"status": "cancelled"}
            except Exception as exc:
                self.logger.error(
                    f"TaskWrapper {self._name} failed with exception: {exc}"
                )
                if self._user_callback:
                    await self._wrapped_callback(
                        None, exc, loop=asyncio.get_running_loop()
                    )
                if self.tracker:
                    await self.tracker.set_failed(self.task_uuid, exc)
                return {"status": "failed", "error": str(exc)}
        elif self.execution_mode == "remote":
            # remote mode — dispatch to a qworker pool via QWorkerTasker.
            # The QWorkerTasker itself handles tracker transitions for the
            # dispatch phase (it was already set to "running" above, so we
            # pass tracker=None here to avoid double-transitions). However,
            # we still let QWorkerTasker manage the done / queued_remote /
            # failed transitions since those depend on remote_mode.
            try:
                if self._tasker is None:
                    # Lazy import so TaskWrapper remains importable without
                    # the [qworker] optional extra installed.
                    from ..taskers.qworker import QWorkerTasker
                    self._tasker = QWorkerTasker(
                        worker_list=self.worker_list,
                        timeout=self.remote_timeout,
                        default_mode=self.remote_mode,
                    )
                response = await self._tasker.dispatch(
                    self.fn,
                    *self.args,
                    remote_mode=self.remote_mode,
                    tracker=self.tracker,
                    task_uuid=self.task_uuid,
                    **self.kwargs,
                )
                self.logger.debug(
                    f"TaskWrapper {self._name} remote dispatch ({self.remote_mode}) completed."
                )
                if self._user_callback:
                    await self._wrapped_callback(
                        response, None, loop=asyncio.get_running_loop()
                    )
                if self.remote_mode == "run":
                    return {"status": "done", "result": response}
                # queue / publish — fire-and-forget; QClient returned an ack.
                return {"status": "queued_remote", "result": response}
            except asyncio.CancelledError:
                self.logger.warning(
                    f"TaskWrapper {self._name} (remote) was cancelled."
                )
                if self.tracker:
                    await self.tracker.set_failed(self.task_uuid, "Cancelled")
                return {"status": "cancelled"}
            except Exception as exc:
                self.logger.error(
                    f"TaskWrapper {self._name} (remote) failed with exception: {exc}"
                )
                if self._user_callback:
                    await self._wrapped_callback(
                        None, exc, loop=asyncio.get_running_loop()
                    )
                # QWorkerTasker already set the tracker to failed; but in case
                # the failure happened before dispatch (e.g. ImportError), make
                # sure the tracker is updated here too.
                if self.tracker:
                    try:
                        await self.tracker.set_failed(self.task_uuid, exc)
                    except Exception:  # noqa: BLE001
                        pass
                return {"status": "failed", "error": str(exc)}
        else:
            # thread mode — run in a dedicated thread with its own event loop.
            # Fire-and-forget: returns {"status": "running"} immediately.
            try:
                async def _finish(result: Any, exc: Exception):
                    """Callback to handle the completion of the coroutine."""
                    if exc:
                        self.logger.error(
                            f"TaskWrapper {self._name} failed with exception: {exc}"
                        )
                        finish_result = {
                            "status": "failed",
                            "error": str(exc)
                        }
                        if self.tracker:
                            await self.tracker.set_failed(self.task_uuid, exc)
                    else:
                        self.logger.debug(
                            f"TaskWrapper {self._name} completed successfully."
                        )
                        finish_result = {
                            "status": "done",
                            "result": result
                        }
                        if self.tracker:
                            await self.tracker.set_done(self.task_uuid, result)
                    return finish_result

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
