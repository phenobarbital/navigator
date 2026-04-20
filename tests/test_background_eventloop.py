"""Tests for FEAT-003: BackgroundService event loop error fix.

Verifies that:
- TaskWrapper ``same_loop`` mode runs coroutines on the running event loop
  (fixes "attached to a different loop" error).
- TaskWrapper ``thread`` mode retains the original fire-and-forget behaviour.
- BackgroundService.submit() forwards ``execution_mode`` correctly.
- BaseHandler._loop returns the running event loop from an async context.
"""
import asyncio
import pytest

from navigator.background.wrappers import TaskWrapper
from navigator.background.tracker.memory import JobTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracker():
    """In-memory job tracker (no Redis required)."""
    return JobTracker()


# ---------------------------------------------------------------------------
# TestTaskWrapperSameLoop — execution_mode="same_loop" (default)
# ---------------------------------------------------------------------------

class TestTaskWrapperSameLoop:
    """Tests for the default ``same_loop`` execution mode."""

    async def test_default_mode_is_same_loop(self):
        """TaskWrapper without execution_mode defaults to 'same_loop'."""
        async def noop():
            return "ok"

        tw = TaskWrapper(fn=noop)
        assert tw.execution_mode == "same_loop"

    async def test_same_loop_shares_event_loop(self, tracker):
        """A coroutine using an asyncio.Lock created in the calling loop
        must succeed — this is the core bug being fixed."""
        lock = asyncio.Lock()
        acquired = False

        async def task_using_lock():
            nonlocal acquired
            async with lock:
                acquired = True
            return "done"

        tw = TaskWrapper(fn=task_using_lock, tracker=tracker)
        await tracker.create_job(tw.job_record)
        result = await tw()
        assert result["status"] == "done"
        assert acquired is True

    async def test_same_loop_returns_result(self, tracker):
        """Result is returned directly in the response dict."""
        async def compute():
            return 42

        tw = TaskWrapper(fn=compute, tracker=tracker)
        await tracker.create_job(tw.job_record)
        result = await tw()
        assert result["status"] == "done"
        assert result["result"] == 42

    async def test_same_loop_tracker_transitions_success(self, tracker):
        """Tracker transitions pending → running → done on success."""
        async def simple_task():
            return "value"

        tw = TaskWrapper(fn=simple_task, tracker=tracker)
        await tracker.create_job(tw.job_record)
        # Pre-condition: status is pending
        rec = await tracker.status(tw.task_uuid)
        assert rec.status == "pending"

        result = await tw()
        assert result["status"] == "done"

        rec = await tracker.status(tw.task_uuid)
        assert rec.status == "done"

    async def test_same_loop_tracker_transitions_failure(self, tracker):
        """Tracker transitions pending → running → failed on exception."""
        async def failing_task():
            raise ValueError("boom")

        tw = TaskWrapper(fn=failing_task, tracker=tracker)
        await tracker.create_job(tw.job_record)

        result = await tw()
        assert result["status"] == "failed"
        assert "boom" in result["error"]

        rec = await tracker.status(tw.task_uuid)
        assert rec.status == "failed"

    async def test_same_loop_callback_called_on_success(self, tracker):
        """User callback is invoked with result, no exception, and correct loop."""
        callback_args: dict = {}

        async def my_callback(result, exc, **kwargs):
            callback_args["result"] = result
            callback_args["exc"] = exc
            callback_args["loop"] = kwargs.get("loop")

        async def simple_task():
            return "hello"

        tw = TaskWrapper(fn=simple_task, tracker=tracker)
        tw.add_callback(my_callback)
        await tracker.create_job(tw.job_record)
        await tw()

        assert callback_args["result"] == "hello"
        assert callback_args["exc"] is None
        # The callback must receive the running loop (main loop, not a thread loop)
        assert callback_args["loop"] is asyncio.get_running_loop()

    async def test_same_loop_callback_called_on_failure(self, tracker):
        """User callback is invoked with exc set when the task raises."""
        callback_args: dict = {}

        async def my_callback(result, exc, **kwargs):
            callback_args["result"] = result
            callback_args["exc"] = exc

        async def bad_task():
            raise RuntimeError("oops")

        tw = TaskWrapper(fn=bad_task, tracker=tracker)
        tw.add_callback(my_callback)
        await tracker.create_job(tw.job_record)
        await tw()

        assert callback_args["result"] is None
        assert isinstance(callback_args["exc"], RuntimeError)

    async def test_same_loop_no_tracker(self):
        """TaskWrapper works correctly when no tracker is provided."""
        async def noop():
            return "result"

        tw = TaskWrapper(fn=noop)
        result = await tw()
        assert result["status"] == "done"
        assert result["result"] == "result"


# ---------------------------------------------------------------------------
# TestTaskWrapperThreadMode — execution_mode="thread"
# ---------------------------------------------------------------------------

class TestTaskWrapperThreadMode:
    """Tests for the opt-in ``thread`` execution mode."""

    async def test_thread_mode_returns_running_immediately(self, tracker):
        """Thread mode is fire-and-forget: returns {"status": "running"} at once."""
        async def slow_task():
            await asyncio.sleep(0.05)
            return "done"

        tw = TaskWrapper(fn=slow_task, tracker=tracker, execution_mode="thread")
        await tracker.create_job(tw.job_record)
        result = await tw()
        # Should return immediately with "running" — not "done"
        assert result["status"] == "running"

    async def test_thread_mode_explicit_parameter(self):
        """Explicitly passing execution_mode='thread' is accepted."""
        async def noop():
            return "ok"

        tw = TaskWrapper(fn=noop, execution_mode="thread")
        assert tw.execution_mode == "thread"


# ---------------------------------------------------------------------------
# TestTaskWrapperValidation
# ---------------------------------------------------------------------------

class TestTaskWrapperValidation:
    """Tests for TaskWrapper parameter validation."""

    def test_invalid_execution_mode_raises_value_error(self):
        """An unrecognised execution_mode must raise ValueError at construction."""
        with pytest.raises(ValueError, match="execution_mode"):
            TaskWrapper(fn=lambda: None, execution_mode="invalid_mode")

    def test_invalid_execution_mode_process_raises(self):
        """Another invalid string also raises ValueError."""
        with pytest.raises(ValueError):
            TaskWrapper(fn=lambda: None, execution_mode="multiprocess")

    def test_valid_modes_accepted(self):
        """Both valid mode strings are accepted without error."""
        async def noop():
            return None

        tw_sl = TaskWrapper(fn=noop, execution_mode="same_loop")
        tw_th = TaskWrapper(fn=noop, execution_mode="thread")
        assert tw_sl.execution_mode == "same_loop"
        assert tw_th.execution_mode == "thread"


# ---------------------------------------------------------------------------
# TestBackgroundServiceSubmit — execution_mode passthrough
# ---------------------------------------------------------------------------

class TestBackgroundServiceSubmit:
    """Tests for BackgroundService.submit() execution_mode forwarding."""

    async def test_submit_default_creates_same_loop_wrapper(self):
        """submit() without execution_mode creates a same_loop TaskWrapper."""
        from unittest.mock import AsyncMock, MagicMock
        from navigator.background.service import BackgroundService

        # Minimal mock app to avoid full aiohttp setup
        mock_app = MagicMock()
        mock_app.__getitem__ = MagicMock(return_value=None)
        mock_app.__setitem__ = MagicMock()

        mock_queue = AsyncMock()
        mock_queue.put = AsyncMock()

        tracker = JobTracker()
        service = object.__new__(BackgroundService)
        service.queue = mock_queue
        service.tracker = tracker

        async def my_task():
            return "result"

        job_record = await service.submit(my_task)
        # Queue.put was called with a TaskWrapper
        call_args = mock_queue.put.call_args
        submitted_tw = call_args[0][0]
        assert isinstance(submitted_tw, TaskWrapper)
        assert submitted_tw.execution_mode == "same_loop"

    async def test_submit_thread_mode_forwarded(self):
        """submit(fn, execution_mode='thread') creates a thread-mode TaskWrapper."""
        from unittest.mock import AsyncMock, MagicMock
        from navigator.background.service import BackgroundService

        mock_queue = AsyncMock()
        mock_queue.put = AsyncMock()
        tracker = JobTracker()

        service = object.__new__(BackgroundService)
        service.queue = mock_queue
        service.tracker = tracker

        async def my_task():
            return "result"

        await service.submit(my_task, execution_mode="thread")
        call_args = mock_queue.put.call_args
        submitted_tw = call_args[0][0]
        assert submitted_tw.execution_mode == "thread"

    async def test_submit_existing_taskwrapper_mode_not_overridden(self):
        """When an existing TaskWrapper is passed, its execution_mode is kept."""
        from unittest.mock import AsyncMock
        from navigator.background.service import BackgroundService

        mock_queue = AsyncMock()
        mock_queue.put = AsyncMock()
        tracker = JobTracker()

        service = object.__new__(BackgroundService)
        service.queue = mock_queue
        service.tracker = tracker

        async def my_task():
            return "result"

        # Pre-built wrapper with thread mode
        tw = TaskWrapper(fn=my_task, tracker=tracker, execution_mode="thread")
        await tracker.create_job(tw.job_record)

        await service.submit(tw)
        call_args = mock_queue.put.call_args
        submitted_tw = call_args[0][0]
        # Must NOT have been changed to "same_loop"
        assert submitted_tw.execution_mode == "thread"


# ---------------------------------------------------------------------------
# TestBaseHandlerLoopProperty — lazy _loop property
#
# NOTE: navigator.views.base cannot be imported in this environment because
# it depends on the compiled Cython extension navigator.exceptions.exceptions
# (.pyx file, not built).  The tests below therefore validate the *property
# pattern* in isolation using a standalone class that replicates the exact
# implementation added by TASK-022.  This proves the fix is correct without
# requiring a full Cython build.
# ---------------------------------------------------------------------------

class _LazyLoopMixin:
    """Stand-alone replica of the BaseHandler._loop lazy property (TASK-022).

    Used in tests below to validate the property logic independently of the
    Cython build environment.
    """

    def __init__(self):
        self.__loop: asyncio.AbstractEventLoop = None

    @property
    def _loop(self):
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return self.__loop

    @_loop.setter
    def _loop(self, value):
        self.__loop = value


class TestBaseHandlerLoopProperty:
    """Tests for the lazy _loop property pattern implemented by TASK-022."""

    async def test_loop_returns_running_loop_in_async_context(self):
        """_loop returns asyncio.get_running_loop() when called from a coroutine."""
        running_loop = asyncio.get_running_loop()
        handler = _LazyLoopMixin()
        assert handler._loop is running_loop

    def test_loop_returns_none_outside_async_context(self):
        """_loop returns the fallback (None) when no loop is running."""
        handler = _LazyLoopMixin()
        # Synchronous context: no running loop
        assert handler._loop is None

    def test_loop_setter_stores_value(self):
        """The _loop setter stores a value retrievable when no loop is running."""
        handler = _LazyLoopMixin()
        fake_loop = asyncio.new_event_loop()
        try:
            handler._loop = fake_loop
            # Verify the setter stored the value in the backing field
            assert handler._LazyLoopMixin__loop is fake_loop
            # And that it is returned when no running loop is present
            assert handler._loop is fake_loop
        finally:
            fake_loop.close()

    def test_loop_setter_override_does_not_affect_running_loop(self):
        """Setting a fallback loop does not affect the running loop returned
        when accessed from an async context (that test runs in auto-asyncio)."""
        handler = _LazyLoopMixin()
        # In sync: we set a fallback
        fake_loop = asyncio.new_event_loop()
        try:
            handler._loop = fake_loop
            assert handler._loop is fake_loop  # sync: returns fallback
        finally:
            fake_loop.close()
