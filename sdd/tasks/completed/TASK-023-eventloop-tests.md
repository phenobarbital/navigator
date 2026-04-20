# TASK-023: Event Loop Fix Tests

**Feature**: FEAT-003 — BackgroundService Event Loop Error Fix
**Spec**: `sdd/specs/backgroundservice-eventloop-error.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-019, TASK-020, TASK-021, TASK-022
**Assigned-to**: unassigned

---

## Context

Tests for the dual execution mode and BaseHandler loop fix. Must verify that
same-loop execution resolves the "attached to a different loop" error, that
thread execution still works for isolated tasks, and that the BaseHandler
property returns the correct loop.

Implements **Spec Module 5**: Tests.

---

## Scope

- Create `tests/test_background_eventloop.py` with:
  1. **Same-loop tests**: verify coroutines sharing asyncio primitives work
  2. **Thread-mode tests**: verify isolated coroutines work via thread path
  3. **Default mode test**: verify `execution_mode` defaults to `"same_loop"`
  4. **Invalid mode test**: verify `ValueError` on bad `execution_mode`
  5. **Callback tests**: verify user callbacks fire correctly in both modes
  6. **Tracker tests**: verify status transitions in both modes
  7. **Service submit tests**: verify `execution_mode` passthrough
  8. **BaseHandler loop test**: verify lazy property returns running loop
- Use `pytest-asyncio` for async test support
- Use in-memory `JobTracker` (no Redis needed)

**NOT in scope**:
- Integration tests with aiohttp test client (would require full app setup)
- Performance benchmarks

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_background_eventloop.py` | CREATE | All event loop fix tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from navigator.background.wrappers import TaskWrapper, coroutine_in_thread  # verified: wrappers/__init__.py:50,15
from navigator.background.tracker.memory import JobTracker  # verified: tracker/memory.py:8
from navigator.background.tracker.models import JobRecord    # verified: tracker/models.py:15
from navigator.background.service import BackgroundService   # verified: service/__init__.py:10
from navigator.background.queue import BackgroundQueue       # verified: queue/__init__.py:35
```

### Existing Signatures to Use (after TASK-019 changes)

```python
# navigator/background/wrappers/__init__.py (AFTER TASK-019)
class TaskWrapper:
    def __init__(
        self,
        fn = None,
        *args,
        execution_mode: str = "same_loop",  # ADDED by TASK-019
        tracker: JobTracker = None,
        jitter: float = 0.0,
        logger = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs
    ):
        self.execution_mode = execution_mode  # ADDED by TASK-019
        self.fn = fn
        self.tracker = tracker
        self.job_record: JobRecord  # auto-created
        self._user_callback = ...

    def add_callback(self, callback):  # line 108
    async def __call__(self) -> dict:  # returns {"status": "done"|"failed"|"running", ...}

# navigator/background/tracker/memory.py
class JobTracker:
    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
    
    async def create_job(self, job, **kwargs) -> JobRecord:
    async def set_running(self, job_id: str) -> None:
    async def set_done(self, job_id: str, result=None) -> None:
    async def set_failed(self, job_id: str, exc: Exception) -> None:
    async def status(self, job_id: str) -> Optional[JobRecord]:
    async def exists(self, job_id: str) -> bool:

# navigator/views/base.py (AFTER TASK-022)
class BaseHandler(ABC):
    @property
    def _loop(self) -> Optional[asyncio.AbstractEventLoop]:
        # returns asyncio.get_running_loop() or fallback
```

### Does NOT Exist

- ~~`TaskWrapper.run()`~~ — not a method; use `await tw()`
- ~~`JobTracker.get(job_id)`~~ — use `status(job_id)`
- ~~`BackgroundService.create_task()`~~ — use `submit()`
- ~~`navigator.background.testing`~~ — no test utilities module
- ~~`pytest.fixture(scope="session") for BackgroundService`~~ — create per-test

---

## Implementation Notes

### Test Structure

```python
import asyncio
import pytest
from navigator.background.wrappers import TaskWrapper
from navigator.background.tracker.memory import JobTracker


@pytest.fixture
def tracker():
    return JobTracker()


class TestTaskWrapperSameLoop:
    """Tests for execution_mode='same_loop' (default)."""

    @pytest.mark.asyncio
    async def test_default_mode_is_same_loop(self):
        async def noop():
            return "ok"
        tw = TaskWrapper(fn=noop)
        assert tw.execution_mode == "same_loop"

    @pytest.mark.asyncio
    async def test_same_loop_shares_event_loop(self, tracker):
        """Coroutine can use asyncio primitives from the calling loop."""
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

    @pytest.mark.asyncio
    async def test_same_loop_tracker_done(self, tracker):
        async def simple_task():
            return 42

        tw = TaskWrapper(fn=simple_task, tracker=tracker)
        await tracker.create_job(tw.job_record)
        result = await tw()
        assert result["status"] == "done"
        rec = await tracker.status(tw.task_uuid)
        assert rec.status == "done"

    @pytest.mark.asyncio
    async def test_same_loop_tracker_failed(self, tracker):
        async def failing_task():
            raise ValueError("boom")

        tw = TaskWrapper(fn=failing_task, tracker=tracker)
        await tracker.create_job(tw.job_record)
        result = await tw()
        assert result["status"] == "failed"
        rec = await tracker.status(tw.task_uuid)
        assert rec.status == "failed"

    @pytest.mark.asyncio
    async def test_same_loop_callback_called(self, tracker):
        callback_args = {}

        async def my_callback(result, exc, **kwargs):
            callback_args['result'] = result
            callback_args['exc'] = exc
            callback_args['loop'] = kwargs.get('loop')

        async def simple_task():
            return "hello"

        tw = TaskWrapper(fn=simple_task, tracker=tracker)
        tw.add_callback(my_callback)
        await tracker.create_job(tw.job_record)
        await tw()
        assert callback_args['result'] == "hello"
        assert callback_args['exc'] is None
        assert callback_args['loop'] is asyncio.get_running_loop()


class TestTaskWrapperThreadMode:
    """Tests for execution_mode='thread'."""

    @pytest.mark.asyncio
    async def test_thread_mode_returns_running(self, tracker):
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"

        tw = TaskWrapper(fn=slow_task, tracker=tracker, execution_mode="thread")
        await tracker.create_job(tw.job_record)
        result = await tw()
        assert result["status"] == "running"  # fire-and-forget


class TestTaskWrapperValidation:

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            TaskWrapper(fn=lambda: None, execution_mode="invalid")


class TestBaseHandlerLoop:
    """Test the lazy _loop property."""

    @pytest.mark.asyncio
    async def test_loop_returns_running_loop(self):
        from navigator.views.base import BaseHandler
        # BaseHandler is ABC, test the property logic
        loop = asyncio.get_running_loop()
        # The property should return the running loop
        # (exact test depends on TASK-022 implementation)
```

### Key Constraints

- All tests must use `pytest-asyncio` with `@pytest.mark.asyncio`
- Use `JobTracker` (in-memory), NOT `RedisJobTracker`
- Thread-mode tests are inherently timing-sensitive — the task returns
  `{"status": "running"}` immediately. Don't assert on final result
  (it completes asynchronously in a thread).
- The `BaseHandler` test may need a concrete subclass since `BaseHandler` is ABC.

---

## Acceptance Criteria

- [ ] All tests pass: `pytest tests/test_background_eventloop.py -v`
- [ ] Same-loop mode: shared asyncio.Lock test passes (proves no loop mismatch)
- [ ] Thread mode: returns `{"status": "running"}` immediately
- [ ] Invalid mode raises `ValueError`
- [ ] Callbacks receive correct `loop` parameter
- [ ] Tracker transitions verified for both success and failure
- [ ] No flaky tests due to thread timing

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/backgroundservice-eventloop-error.spec.md`
2. **Check dependencies** — verify TASK-019 through TASK-022 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read the actual changed files to confirm signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the tests
6. **Run**: `source .venv/bin/activate && pytest tests/test_background_eventloop.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-04-20
**Notes**: 20 tests created, all passing. BaseHandler tests use standalone _LazyLoopMixin class (can't import navigator.views.base due to uncompiled Cython exceptions.pyx). Thread-mode test fires and returns "running" as expected; background thread warning is benign.

**Deviations from spec**: BaseHandler tests test the property pattern in isolation rather than importing BaseHandler directly (Cython build issue in test environment).
