# Feature Specification: BackgroundService Event Loop Error Fix

**Feature ID**: FEAT-003
**Date**: 2026-04-20
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`BackgroundService` tasks that invoke async operations sharing application state
(agent calls, database queries, HTTP sessions) intermittently fail with:

```
RuntimeError: Task <Task pending name='Task-8091'
  coro=<NextStopAgent._team_performance() running at handler.py:620>
  cb=[run_until_complete.<locals>.done_cb()]>
  got Future <Future pending cb=[_chain_future.<locals>._call_check_cancel()
  at .../asyncio/futures.py:387]> attached to a different loop
```

**Root cause**: `coroutine_in_thread()` creates a **new event loop** in a
**new thread** for every task. The user's coroutine runs in this fresh loop, but
it internally awaits operations on objects (HTTP client sessions, DB connection
pools, asyncio Locks) that were created in the **main aiohttp event loop**. These
asyncio primitives are bound to their creation loop and cannot be used from a
different one.

**Execution flow that triggers the bug**:

```
Main loop (aiohttp)
  └─ request handler → register_background_task()
       └─ BackgroundService.submit(task_wrapper)
            └─ BackgroundQueue.process_queue() [consumer, still main loop]
                 └─ _execute_taskwrapper(tw) → tw.__call__()
                      └─ coroutine_in_thread(coro)      ← HERE
                           └─ Thread + asyncio.new_event_loop()
                                └─ coro runs in NEW loop
                                     └─ awaits Future from MAIN loop → CRASH
```

The `coroutine_in_thread()` design is correct **only** for fully self-contained
coroutines that create all their own asyncio resources. It is incorrect for
coroutines that share state with the aiohttp application (which is the common
case for agent handlers).

### Goals

- **G1**: Background tasks that share application state (agents, DB pools, HTTP
  sessions) run reliably without event loop mismatches.
- **G2**: Provide a same-loop execution path (`asyncio.create_task`) as the
  default for `TaskWrapper`, since most background tasks need shared state.
- **G3**: Retain the thread-based execution path (`coroutine_in_thread`) as an
  opt-in for truly isolated, CPU-bound, or blocking work.
- **G4**: Fix the deprecated `asyncio.get_event_loop()` call in `BaseHandler`
  to prevent stale loop references.
- **G5**: No breaking changes to the existing `register_background_task()` API
  in `AgentHandler`.

### Non-Goals (explicitly out of scope)

- Rewriting the entire `BackgroundQueue` consumer architecture.
- Adding multiprocessing-based task execution.
- Changing the `JobTracker` / `RedisJobTracker` storage model.
- Modifying the `AgentHandler` class itself (fix is in navigator core).

---

## 2. Architectural Design

### Overview

Introduce a **dual execution mode** in `TaskWrapper`:

1. **`same_loop`** (default): Use `asyncio.create_task()` to schedule the
   coroutine on the running event loop. The consumer awaits the resulting Task.
   This shares the event loop with aiohttp, so all application-scoped asyncio
   objects work correctly.

2. **`thread`** (opt-in): Use the existing `coroutine_in_thread()` for coroutines
   that are fully self-contained or need true thread isolation.

```
BackgroundQueue.process_queue()  [runs in main event loop]
  └─ _execute_taskwrapper(tw)
       └─ tw.__call__()
            ├─ mode="same_loop" → asyncio.create_task(coro)  ← await result
            └─ mode="thread"   → coroutine_in_thread(coro)   ← fire-and-forget + callback
```

### Component Diagram

```
AgentHandler.register_background_task()
       │
       ▼
 BackgroundService.submit(TaskWrapper)
       │
       ▼
 BackgroundQueue ──put──► asyncio.Queue
       │
       ▼
 Consumer (process_queue)
       │
       ▼
 _execute_taskwrapper(tw)
       │
       ▼
 TaskWrapper.__call__()
       │
       ├── execution_mode == "same_loop"
       │      └─► asyncio.create_task(fn(*args, **kwargs))
       │          └─► await task (shares main loop)
       │
       └── execution_mode == "thread"
              └─► coroutine_in_thread(coro, callback, on_complete)
                  └─► new Thread + new event loop (isolated)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TaskWrapper` | modified | Add `execution_mode` parameter |
| `TaskWrapper.__call__` | modified | Dual-path execution logic |
| `coroutine_in_thread` | unchanged | Retained for thread mode |
| `BackgroundService.submit` | modified | Pass through `execution_mode` kwarg |
| `BaseHandler.__init__` | modified | Replace deprecated `get_event_loop()` |
| `BackgroundQueue._execute_taskwrapper` | modified | Remove redundant `ThreadPoolExecutor` wrapper |

### Data Models

No new data models. `JobRecord` is unchanged.

### New Public Interfaces

```python
# navigator/background/wrappers/__init__.py

class TaskWrapper:
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        execution_mode: str = "same_loop",  # NEW: "same_loop" | "thread"
        tracker: JobTracker = None,
        jitter: float = 0.0,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs
    ): ...

    async def __call__(self) -> dict:
        """Execute the wrapped function.
        
        If execution_mode == "same_loop": creates an asyncio.Task on the
        running loop, awaits it, and returns the result directly.
        
        If execution_mode == "thread": delegates to coroutine_in_thread()
        (existing fire-and-forget behavior).
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: TaskWrapper Dual Execution Mode
- **Path**: `navigator/background/wrappers/__init__.py`
- **Responsibility**:
  - Add `execution_mode` parameter to `TaskWrapper.__init__()`.
  - Implement same-loop execution path in `__call__()` using `asyncio.create_task()`.
  - In same-loop mode: await the task, call callbacks, update tracker directly.
  - In thread mode: preserve existing `coroutine_in_thread()` behavior.
  - Remove the unused `ThreadPoolExecutor(max_workers=1)` context manager in `__call__()`.
- **Depends on**: nothing

### Module 2: BackgroundService submit() passthrough
- **Path**: `navigator/background/service/__init__.py`
- **Responsibility**:
  - Pass `execution_mode` kwarg through to `TaskWrapper` when creating one.
  - Default to `"same_loop"` when not specified.
- **Depends on**: Module 1

### Module 3: BackgroundQueue cleanup
- **Path**: `navigator/background/queue/__init__.py`
- **Responsibility**:
  - Remove the redundant `ThreadPoolExecutor(max_workers=1)` in
    `_execute_taskwrapper()` (the executor is created but never used — the
    TaskWrapper's `__call__` does its own dispatch).
  - Ensure `_execute_taskwrapper` properly awaits the TaskWrapper result in
    both execution modes.
- **Depends on**: Module 1

### Module 4: BaseHandler event loop fix
- **Path**: `navigator/views/base.py`
- **Responsibility**:
  - Replace `self._loop = asyncio.get_event_loop()` (deprecated, line 51) with
    a lazy property that calls `asyncio.get_running_loop()` when accessed from
    an async context.
  - This prevents stale loop references when the handler is instantiated before
    the event loop is running.
- **Depends on**: nothing (independent of Modules 1-3)

### Module 5: Tests
- **Path**: `tests/test_background_eventloop.py`
- **Responsibility**:
  - Test same-loop execution: coroutine sharing an asyncio.Lock with the caller.
  - Test thread execution: coroutine that creates its own resources.
  - Test that `execution_mode="same_loop"` is the default.
  - Test callbacks and tracker updates work in both modes.
  - Test that the BaseHandler loop property returns the running loop.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_taskwrapper_default_mode` | Module 1 | Default `execution_mode` is `"same_loop"` |
| `test_taskwrapper_same_loop_shares_loop` | Module 1 | Coroutine runs in the same event loop as caller |
| `test_taskwrapper_same_loop_with_shared_lock` | Module 1 | Coroutine can use an `asyncio.Lock` created in the main loop |
| `test_taskwrapper_same_loop_callback` | Module 1 | User callback is invoked with correct args in same-loop mode |
| `test_taskwrapper_same_loop_tracker_updates` | Module 1 | Tracker transitions: pending → running → done |
| `test_taskwrapper_same_loop_error` | Module 1 | Exception in coroutine sets tracker to failed |
| `test_taskwrapper_thread_mode` | Module 1 | `execution_mode="thread"` uses `coroutine_in_thread` |
| `test_taskwrapper_invalid_mode` | Module 1 | Invalid `execution_mode` raises `ValueError` |
| `test_service_submit_passes_mode` | Module 2 | `BackgroundService.submit()` forwards `execution_mode` |
| `test_basehandler_loop_property` | Module 4 | `_loop` returns `asyncio.get_running_loop()` when in async |

### Integration Tests

| Test | Description |
|---|---|
| `test_background_task_end_to_end_same_loop` | Submit task via BackgroundService, verify tracker shows done |
| `test_background_task_with_shared_state` | Task uses shared asyncio primitive without error |

### Test Data / Fixtures

```python
@pytest.fixture
def tracker():
    return JobTracker()

@pytest.fixture
def shared_lock():
    return asyncio.Lock()

@pytest.fixture
async def background_service(aiohttp_app):
    return aiohttp_app['background_service']
```

---

## 5. Acceptance Criteria

- [ ] Background tasks using `execution_mode="same_loop"` (default) can await
      Futures/Tasks/Locks created in the main event loop without error.
- [ ] Background tasks using `execution_mode="thread"` retain existing behavior
      for fully isolated coroutines.
- [ ] `register_background_task()` in downstream `AgentHandler` works without
      code changes (backward compatible).
- [ ] `BaseHandler._loop` returns the running loop, not a potentially stale one.
- [ ] All new tests pass (`pytest tests/test_background_eventloop.py -v`).
- [ ] Existing background service tests continue to pass.
- [ ] No regressions in `BackgroundQueue` consumer behavior.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from navigator.background import BackgroundService, TaskWrapper, JobRecord  # verified: navigator/background/__init__.py:1-5
from navigator.background import BackgroundQueue, BackgroundTask, SERVICE_NAME  # verified: navigator/background/__init__.py:5
from navigator.background.wrappers import TaskWrapper, coroutine_in_thread  # verified: navigator/background/wrappers/__init__.py:50,15
from navigator.background.tracker import JobTracker, RedisJobTracker, JobRecord  # verified: navigator/background/tracker/__init__.py
from navigator.background.tracker.models import JobRecord, gen_uuid, time_now  # verified: navigator/background/tracker/models.py:15,7,12
from navigator.background.tracker.memory import JobTracker  # verified: navigator/background/tracker/memory.py:8
from navigator.background.service import BackgroundService  # verified: navigator/background/service/__init__.py:10
from navigator.background.queue import BackgroundQueue  # verified: navigator/background/queue/__init__.py:35
from navigator.views.base import BaseHandler, BaseView  # verified: navigator/views/base.py:42,596
```

### Existing Class Signatures

```python
# navigator/background/wrappers/__init__.py
def coroutine_in_thread(
    coro: coroutine,
    callback: Optional[coroutine] = None,
    on_complete: OnCompleteFn = None,
) -> threading.Event:  # line 15
    """Run a coroutine in a new thread with its own event loop."""
    parent_loop = asyncio.get_running_loop()  # line 21 — captures MAIN loop
    # ... creates new_loop in thread, runs coro, calls back ...

class TaskWrapper:  # line 50
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        tracker: JobTracker = None,           # line 59
        jitter: float = 0.0,                  # line 60
        logger: Optional[logging.Logger] = None,  # line 61
        max_retries: int = 0,                 # line 62
        retry_delay: float = 0.0,             # line 63
        **kwargs
    ):  # line 55
        self.fn = fn                          # line 66
        self.tracker = tracker                # line 67
        self._name: str = ...                 # line 68
        self._user_callback = ...             # line 69
        self.jitter: float = jitter           # line 76
        self.job_record: JobRecord = ...      # line 84
        self.args = args                      # line 98
        self.kwargs = kwargs                  # line 99

    @property
    def task_uuid(self) -> uuid.UUID:  # line 101

    def add_callback(self, callback):  # line 108

    async def _wrapped_callback(self, result, exc, loop):  # line 119

    async def __call__(self):  # line 140
        # Current impl: always uses coroutine_in_thread() at line 193
        # Creates unused ThreadPoolExecutor at line 189


# navigator/background/service/__init__.py
class BackgroundService:  # line 10
    def __init__(
        self,
        app: web.Application,
        queue: Optional[BackgroundQueue] = None,
        tracker: Optional[JobTracker] = None,
        tracker_type: str = 'memory',
        **kwargs
    ) -> None:  # line 15
        self.queue = ...                      # line 23
        self.tracker = ...                    # line 25

    async def submit(
        self,
        fn: Union[Callable, TaskWrapper],
        *args,
        jitter: float = 0.0,
        **kwargs
    ) -> uuid.UUID:  # line 41
        # Creates TaskWrapper at line 57 if fn is not already one
        # Puts tw in queue at line 73

    async def status(self, task_id) -> Optional[str]:  # line 76
    async def record(self, task_id) -> Optional[JobRecord]:  # line 92


# navigator/background/queue/__init__.py
class BackgroundQueue:  # line 35
    def __init__(
        self,
        app: Optional[web.Application],
        max_workers: int = 5,
        coro_in_threads: bool = True,
        **kwargs
    ) -> None:  # line 47
        self.queue = asyncio.Queue(maxsize=...)     # line 60
        self.consumers: list = []                   # line 63
        self.executor = ThreadPoolExecutor(...)     # line 85

    async def put(self, fn, *args, **kwargs):       # line 116
    async def process_queue(self):                  # line 257
    async def _execute_taskwrapper(self, task):     # line 178
        # Creates redundant ThreadPoolExecutor at line 181
    async def fire_consumers(self):                 # line 340


# navigator/background/tracker/models.py
class JobRecord(BaseModel):  # line 15
    task_id: str = Field(default=gen_uuid)          # line 20
    name: str = None                                # line 21
    content: Optional[str] = None                   # line 22
    status: str = 'pending'                         # line 23
    attributes: Dict[str, Any] = ...                # line 24
    result: Optional[Any] = None                    # line 25/30
    error: Optional[str] = None                     # line 26/31
    created_at: datetime = ...                      # line 27
    started_at: Optional[int]                       # line 28
    finished_at: Optional[int]                      # line 29
    stacktrace: Optional[str] = None                # line 32


# navigator/background/tracker/memory.py
class JobTracker:  # line 8
    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}       # line 14
        self._lock = asyncio.Lock()                 # line 15

    async def create_job(self, job, **kwargs):       # line 20
    async def set_running(self, job_id):             # line 32
    async def set_done(self, job_id, result=None):   # line 38
    async def set_failed(self, job_id, exc):         # line 45
    async def status(self, job_id):                  # line 52
    async def exists(self, job_id):                  # line 60


# navigator/views/base.py
class BaseHandler(ABC):  # line 42
    def __init__(self, *args, **kwargs):  # line 48
        self._loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()  # line 51 ← DEPRECATED
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TaskWrapper(execution_mode=...)` | `TaskWrapper.__init__()` | new parameter | `wrappers/__init__.py:55` |
| `TaskWrapper.__call__()` same_loop path | `asyncio.create_task()` | stdlib | `wrappers/__init__.py:140` |
| `TaskWrapper.__call__()` thread path | `coroutine_in_thread()` | existing function | `wrappers/__init__.py:15` |
| `BackgroundService.submit()` | `TaskWrapper.__init__()` | kwarg passthrough | `service/__init__.py:57` |
| `BaseHandler._loop` | `asyncio.get_running_loop()` | property replacement | `views/base.py:51` |

### Does NOT Exist (Anti-Hallucination)

- ~~`TaskWrapper.execution_mode`~~ — does not exist yet (to be added)
- ~~`TaskWrapper.run_in_loop()`~~ — not a real method
- ~~`BackgroundService.execute()`~~ — not a real method; use `submit()`
- ~~`BackgroundQueue.run_task()`~~ — not a real method
- ~~`coroutine_in_thread.parent_loop`~~ — local variable, not an attribute
- ~~`JobTracker.get_job()`~~ — use `status()` to get a JobRecord
- ~~`JobRecord.loop`~~ — JobRecord has no event loop reference
- ~~`BaseHandler.get_loop()`~~ — not a method; `_loop` is a direct attribute

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Same-loop execution must properly handle exceptions**: Wrap `asyncio.create_task()`
  result in try/except, update tracker on failure, call user callbacks.
- **Callbacks in same-loop mode**: Call `_wrapped_callback(result, exc, loop=running_loop)`
  directly (no need for `run_coroutine_threadsafe` since we're already in the main loop).
- **`_finish()` in same-loop mode**: Call it directly as a coroutine, not via
  `run_coroutine_threadsafe`.
- Use `asyncio.get_running_loop()` (not `get_event_loop()`) everywhere.

### Known Risks / Gotchas

- **Long-running same-loop tasks block the consumer**: Since same-loop tasks
  share the event loop with aiohttp, a CPU-bound task will block request
  handling. Mitigate: document that `execution_mode="thread"` should be used
  for CPU-bound work. The consumer pool (multiple consumers) provides some
  concurrency but all share one thread (the main event loop thread).
- **Callback signature change**: The `_wrapped_callback` currently receives
  `loop=new_loop` (the thread's loop). In same-loop mode it should receive
  `loop=running_loop` (the main loop). User callbacks that depend on getting a
  fresh loop for creating resources will behave differently. This is acceptable
  since the old behavior was buggy.
- **Backward compatibility**: Existing code that does NOT pass `execution_mode`
  gets `"same_loop"` (new default). This is a behavior change from the old
  default (thread-based). However, the old default was causing the bug, so this
  is intentional. If any user specifically needs thread isolation, they must
  now pass `execution_mode="thread"` explicitly.

### External Dependencies

No new external dependencies required.

---

## 8. Open Questions

- [x] Should `"same_loop"` be the default? — **Yes**, because the common case
  is agent tasks that share application state. Thread mode was causing the bug.
- [ ] Should we add a `timeout` parameter for same-loop tasks to prevent
  indefinite blocking? — *Owner: Jesus* — Can be deferred to a follow-up.
- [ ] Should `BaseHandler._loop` be removed entirely or kept as a lazy property?
  — *Owner: Jesus* — Keeping as a lazy property avoids breaking subclasses that
  reference `self._loop`.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All 5 modules are tightly coupled — Module 1 must land first, then 2-3 in
  either order, Module 4 is independent, Module 5 last.
- **Cross-feature dependencies**: None. This is a bugfix in navigator core.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Jesus Lara | Initial draft |
