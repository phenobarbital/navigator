# Feature Specification: QWorker Background Tasker

**Feature ID**: FEAT-004
**Date**: 2026-04-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Navigator's `BackgroundService` can only execute tasks **locally** — either on the
same event loop (`same_loop`) or in a dedicated thread (`thread`). There is no way
to offload a background task to a **remote worker process** managed by
[qworker](https://github.com/phenobarbital/qworker).

Teams running compute-heavy or long-running background work (report generation,
ML inference, large data transforms) need to push tasks to a pool of remote
`qworker` instances so the aiohttp process stays responsive.

### Goals

- **G1**: Add a `QWorkerTasker` class that sends jobs to remote qworker workers
  via `QClient`, fully integrated with Navigator's existing tracker system.
- **G2**: Support three dispatch modes:
  - `run` — send & wait for result (via `QClient.run()`),
  - `queue` — send to TCP queue, fire-and-forget (via `QClient.queue()`),
  - `publish` — send to Redis Stream, fire-and-forget (via `QClient.publish()`).
- **G3**: Add a new `execution_mode = "remote"` to `TaskWrapper` so that
  `BackgroundService.submit()` can transparently route tasks to qworker.
- **G4**: Add `qworker` as an optional extra (`navigator-api[qworker]`) so the
  dependency is only pulled in when needed.
- **G5**: Track remote job status through Navigator's existing `JobTracker`.

### Non-Goals (explicitly out of scope)

- Building a persistent result backend inside qworker (qworker returns results
  synchronously via TCP for `run()` mode; `queue`/`publish` are fire-and-forget).
- Adding qworker server management or auto-discovery to Navigator.
- Modifying qworker's own code.
- Adding a UI or admin dashboard for remote job monitoring.

---

## 2. Architectural Design

### Overview

A new `QWorkerTasker` class wraps `qw.client.QClient` and plugs into the
existing `BackgroundQueue` dispatch pipeline. When a `TaskWrapper` has
`execution_mode="remote"`, the queue delegates execution to `QWorkerTasker`
instead of running locally.

### Component Diagram

```
BackgroundService.submit(fn, execution_mode="remote", remote_mode="run")
  │
  ├─ wraps fn in TaskWrapper(execution_mode="remote", remote_mode="run")
  │
  └─ BackgroundQueue.put(task_wrapper)
       │
       └─ process_queue() → _execute_taskwrapper(task)
            │
            └─ task.__call__()  [execution_mode == "remote"]
                 │
                 └─ QWorkerTasker.dispatch(fn, *args, **kwargs)
                      │
                      ├─ remote_mode="run"     → QClient.run()     → result (sync)
                      ├─ remote_mode="queue"   → QClient.queue()   → {"status": "Queued"}
                      └─ remote_mode="publish" → QClient.publish() → {"status": "Queued"}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TaskWrapper` | extends | Add `"remote"` to `VALID_EXECUTION_MODES`; add `remote_mode` and `worker_list` params |
| `BackgroundQueue._execute_taskwrapper()` | uses | No change needed — already calls `await task()` |
| `BackgroundService.submit()` | uses | Forward `remote_mode` and `worker_list` kwargs to TaskWrapper |
| `JobTracker` / `RedisJobTracker` | uses | QWorkerTasker updates tracker on dispatch/completion |
| `qw.client.QClient` | wraps | Lazy-imported to avoid hard dependency |

### Data Models

```python
# No new Pydantic models needed.
# QWorkerTasker uses the existing JobRecord for tracking.
# Remote dispatch parameters are passed as TaskWrapper kwargs.
```

### New Public Interfaces

```python
class QWorkerTasker:
    """Sends tasks to remote qworker instances via QClient."""

    def __init__(
        self,
        worker_list: list[tuple[str, int]] | None = None,
        timeout: int = 5,
        default_mode: str = "run",
    ) -> None: ...

    async def dispatch(
        self,
        fn: Callable,
        *args,
        remote_mode: str = None,  # "run" | "queue" | "publish"
        **kwargs,
    ) -> Any: ...

    async def close(self) -> None: ...
```

Usage from handler code:

```python
# Mode 1: run — wait for result from remote worker
result = await service.submit(
    my_heavy_function, arg1, arg2,
    execution_mode="remote",
    remote_mode="run",
)

# Mode 2: queue — fire-and-forget via TCP
job = await service.submit(
    my_heavy_function, arg1, arg2,
    execution_mode="remote",
    remote_mode="queue",
)

# Mode 3: publish — fire-and-forget via Redis Streams
job = await service.submit(
    my_heavy_function, arg1, arg2,
    execution_mode="remote",
    remote_mode="publish",
)
```

---

## 3. Module Breakdown

### Module 1: QWorkerTasker

- **Path**: `navigator/background/taskers/qworker.py`
- **Responsibility**: Wraps `qw.client.QClient`. Provides `dispatch()` which
  delegates to `QClient.run()`, `.queue()`, or `.publish()` based on
  `remote_mode`. Updates tracker status. Lazy-imports `qw` so the module
  is importable even without the `[qworker]` extra (raises at construction
  time with a helpful message).
- **Depends on**: `qw.client.QClient` (optional extra), `JobTracker`

### Module 2: TaskWrapper Remote Mode

- **Path**: `navigator/background/wrappers/__init__.py` (modify existing)
- **Responsibility**: Add `"remote"` to `VALID_EXECUTION_MODES`. Accept
  `remote_mode`, `worker_list`, `remote_timeout` kwargs. In `__call__()`,
  delegate to `QWorkerTasker.dispatch()` when `execution_mode == "remote"`.
- **Depends on**: Module 1

### Module 3: BackgroundService Integration

- **Path**: `navigator/background/service/__init__.py` (modify existing)
- **Responsibility**: Extract and forward `remote_mode`, `worker_list`,
  `remote_timeout` kwargs from `submit()` to `TaskWrapper`. Create/cache a
  shared `QWorkerTasker` instance when first needed.
- **Depends on**: Module 1, Module 2

### Module 4: Package Wiring

- **Path**: `navigator/background/taskers/__init__.py` (new),
  `pyproject.toml` (modify)
- **Responsibility**: Create the `taskers` subpackage. Add `qworker>=2.0.0`
  to a new `[qworker]` optional extra in `pyproject.toml`. Export
  `QWorkerTasker` from the `taskers` package.
- **Depends on**: Module 1

### Module 5: Tests

- **Path**: `tests/test_qworker_tasker.py`
- **Responsibility**: Unit tests for QWorkerTasker (mocked QClient),
  integration tests for TaskWrapper remote mode, end-to-end tests for
  BackgroundService.submit() with remote mode.
- **Depends on**: Module 1, 2, 3, 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_qworker_tasker_init` | Module 1 | Validates QWorkerTasker creation with custom worker_list |
| `test_qworker_tasker_missing_dep` | Module 1 | Raises ImportError with helpful message when qworker not installed |
| `test_dispatch_run_mode` | Module 1 | Mocked QClient.run() returns result; tracker updated to done |
| `test_dispatch_queue_mode` | Module 1 | Mocked QClient.queue() returns Queued; tracker updated |
| `test_dispatch_publish_mode` | Module 1 | Mocked QClient.publish() returns Queued; tracker updated |
| `test_dispatch_run_exception` | Module 1 | QClient.run() raises; tracker set to failed |
| `test_dispatch_invalid_mode` | Module 1 | Raises ValueError for unknown remote_mode |
| `test_taskwrapper_remote_mode` | Module 2 | TaskWrapper(execution_mode="remote") calls QWorkerTasker.dispatch |
| `test_taskwrapper_remote_validates` | Module 2 | TaskWrapper rejects remote mode without remote_mode kwarg |
| `test_submit_remote` | Module 3 | BackgroundService.submit() with execution_mode="remote" routes correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_run_mode` | Submit task via BackgroundService with remote/run, verify result via tracker |
| `test_end_to_end_queue_mode` | Submit with remote/queue, verify tracker shows "queued" |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_qclient(monkeypatch):
    """Mock QClient to avoid needing a real qworker instance."""
    from unittest.mock import AsyncMock, MagicMock
    client = MagicMock()
    client.run = AsyncMock(return_value={"result": 42})
    client.queue = AsyncMock(return_value={"status": "Queued", "task": "fn", "message": "ok"})
    client.publish = AsyncMock(return_value={"status": "Queued", "task": "fn", "message": "stream-id"})
    return client
```

---

## 5. Acceptance Criteria

- [x] `QWorkerTasker` class exists at `navigator/background/taskers/qworker.py`
- [x] `QWorkerTasker.dispatch()` supports `run`, `queue`, and `publish` modes
- [x] `TaskWrapper` accepts `execution_mode="remote"` and delegates to QWorkerTasker
- [x] `BackgroundService.submit()` forwards remote-related kwargs transparently
- [x] `qworker>=2.0.0` is listed under `[project.optional-dependencies]` as `qworker` extra
- [x] Importing `navigator.background` without qworker installed does NOT raise ImportError
- [x] All unit tests pass with mocked QClient
- [x] Tracker status updated correctly for all three remote modes:
  - `run`: pending → running → done/failed
  - `queue`: pending → running → queued
  - `publish`: pending → running → queued
- [x] No breaking changes to existing `same_loop` / `thread` execution modes

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# navigator/background/wrappers/__init__.py — existing, verified
from navigator.background.wrappers import TaskWrapper       # navigator/background/__init__.py:3
from navigator.background.wrappers import coroutine_in_thread  # navigator/background/wrappers/__init__.py:17

# navigator/background/service/__init__.py — existing, verified
from navigator.background.service import BackgroundService   # navigator/background/__init__.py:4

# navigator/background/queue/__init__.py — existing, verified
from navigator.background.queue import BackgroundQueue       # navigator/background/__init__.py:5

# navigator/background/tracker — existing, verified
from navigator.background.tracker import JobTracker          # navigator/background/__init__.py:2
from navigator.background.tracker import RedisJobTracker     # navigator/background/__init__.py:2
from navigator.background.tracker import JobRecord           # navigator/background/__init__.py:2

# qworker — external package, lazy-import only
from qw.client import QClient       # qw/client.py:58
from qw.wrappers import FuncWrapper  # qw/wrappers/func.py:7
```

### Existing Class Signatures

```python
# navigator/background/wrappers/__init__.py
VALID_EXECUTION_MODES = ("same_loop", "thread")  # line 14

class TaskWrapper:                                # line 52
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        execution_mode: str = "same_loop",        # line 76
        tracker: JobTracker = None,               # line 77
        jitter: float = 0.0,                      # line 78
        logger: Optional[logging.Logger] = None,  # line 79
        max_retries: int = 0,                     # line 80
        retry_delay: float = 0.0,                 # line 81
        **kwargs
    ): ...

    @property
    def task_uuid(self) -> uuid.UUID: ...         # line 125

    async def __call__(self):                     # line 165
        # dispatches based on self.execution_mode
        # "same_loop" → asyncio.create_task()     # line 201
        # "thread" → coroutine_in_thread()        # line 235
        ...

# navigator/background/service/__init__.py
class BackgroundService:                          # line 10
    def __init__(
        self,
        app: web.Application,
        queue: Optional[BackgroundQueue] = None,
        tracker: Optional[JobTracker] = None,
        tracker_type: str = 'memory',             # line 17
        **kwargs
    ): ...

    async def submit(
        self,
        fn: Union[Callable, TaskWrapper],
        *args,
        jitter: float = 0.0,
        **kwargs
    ) -> uuid.UUID: ...                           # line 51
    # extracts execution_mode from kwargs at line 78

# navigator/background/tracker/models.py
class JobRecord(BaseModel):                       # line 15
    task_id: str = Field(default=gen_uuid)        # line 16
    name: str = None                              # line 17
    status: str = 'pending'                       # line 20
    result: Optional[Any] = None                  # line 22

# navigator/background/tracker/memory.py
class JobTracker:                                 # line 12
    async def create_job(self, job: JobRecord, **kwargs) -> JobRecord: ...  # line 71
    async def set_running(self, job_id: str) -> None: ...                  # line 83
    async def set_done(self, job_id: str, result: Any = None) -> None: ... # line 89
    async def set_failed(self, job_id: str, exc: Exception) -> None: ...   # line 96
    async def status(self, job_id: str) -> Optional[JobRecord]: ...        # line 103

# qw/client.py
class QClient:                                    # line 58
    def __init__(self, worker_list: list = None, timeout: int = 5): ...  # line 72

    async def run(self, fn: Any, *args, use_wrapper: bool = False, **kwargs): ...  # line 326
    # Synchronous: sends task, waits for result, returns it.

    async def queue(self, fn: Any, *args, use_wrapper: bool = True, **kwargs): ...  # line 420
    # Fire-and-forget via TCP. Returns {"status": "Queued", ...}.

    async def publish(self, fn: Any, *args, use_wrapper: bool = True, **kwargs): ...  # line 484
    # Fire-and-forget via Redis Streams. Returns {"status": "Queued", ...}.

# qw/wrappers/func.py
class FuncWrapper(QueueWrapper):                  # line 7
    def __init__(self, host, func, *args, **kwargs): ...  # line 9
    # host (str): hostname of the sender
    # func (Callable): the function to execute
    async def __call__(self): ...                 # line 15

# qw/wrappers/base.py
class QueueWrapper:                               # line 10
    def __init__(self, coro=None, *args, **kwargs): ...  # line 14
    # kwargs: queued (bool), debug (bool), id (uuid.UUID)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QWorkerTasker` | `QClient.run()` | method call | `qw/client.py:326` |
| `QWorkerTasker` | `QClient.queue()` | method call | `qw/client.py:420` |
| `QWorkerTasker` | `QClient.publish()` | method call | `qw/client.py:484` |
| `QWorkerTasker` | `JobTracker.set_running()` | method call | `navigator/background/tracker/memory.py:83` |
| `QWorkerTasker` | `JobTracker.set_done()` | method call | `navigator/background/tracker/memory.py:89` |
| `QWorkerTasker` | `JobTracker.set_failed()` | method call | `navigator/background/tracker/memory.py:96` |
| `TaskWrapper.__call__()` | `QWorkerTasker.dispatch()` | new delegation | Added in Module 2 |
| `BackgroundService.submit()` | `TaskWrapper(remote_mode=...)` | kwarg forwarding | `navigator/background/service/__init__.py:78` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator.background.taskers`~~ — package does not exist yet (Module 4 creates it)
- ~~`navigator.background.wrappers.RemoteWrapper`~~ — no such class
- ~~`QClient.run_async()`~~ — not a real method; `run()` is already async but waits for result
- ~~`QClient.status(task_id)`~~ — QClient has no per-task status tracking
- ~~`QClient.result(task_id)`~~ — QClient has no result store; results returned inline from `run()`
- ~~`FuncWrapper.result`~~ — FuncWrapper has no result attribute
- ~~`qw.client.QClient.connect()`~~ — no explicit connect; connections made per-call in `get_worker_connection()`
- ~~`navigator.background.service.BackgroundService.tasker`~~ — no tasker attribute exists yet
- ~~`VALID_EXECUTION_MODES` containing `"remote"`~~ — currently only `("same_loop", "thread")`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy import for qworker**: `QWorkerTasker.__init__()` must `import qw.client`
  inside the method body, not at module level. If `qw` is missing, raise
  `ImportError("Install qworker: pip install navigator-api[qworker]")`.
- **Singleton QClient per service**: `BackgroundService` should cache a single
  `QWorkerTasker` instance (created on first remote submit) to reuse TCP
  connections across requests.
- **Tracker integration**: For `run` mode, update tracker to `done` with the
  actual result. For `queue`/`publish` modes, update tracker to a custom status
  `"queued_remote"` since we can't know when the remote worker finishes.
- **No blocking I/O**: `QClient.run()` is already async (uses `asyncio`
  StreamReader/Writer), so it's safe to await in the event loop.

### Known Risks / Gotchas

- **`queue`/`publish` modes are fire-and-forget**: qworker has no built-in
  result backend or completion callback for these modes. The tracker will show
  `"queued_remote"` but never transition to `"done"` unless we add a callback
  mechanism in the future. Document this clearly.
- **Serialization**: qworker uses `cloudpickle` to serialize functions. Closures
  capturing large application state (DB pools, HTTP sessions) will fail. Tasks
  sent remotely must be **self-contained** — document this requirement.
- **`QClient.run()` with `use_wrapper=False`**: By default, `run()` sends the
  raw function via `partial()`, not wrapped in `FuncWrapper`. Set
  `use_wrapper=False` for `run` mode (we want the result back, not queue
  behavior). Use `use_wrapper=True` for `queue`/`publish`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `qworker` | `>=2.0.0` | Remote task dispatch via QClient |

---

## 8. Open Questions

- [x] **Q1**: Should `remote_mode` default to `"run"` (wait for result) or
  `"queue"` (fire-and-forget)? **Decision: default to `"run"`** since it's the
  safest mode (caller gets confirmation of success/failure).
- [x] **Q2**: Should we add an optional polling mechanism for `queue`/`publish`
  modes using `QClient.info()` to check worker state? This would add complexity
  but provide some observability. — *Owner: Jesus*: publish with info.
- [x] **Q3**: Should `QWorkerTasker` support specifying a particular worker
  (by host:port) for a task, or always use round-robin? — *Owner: Jesus*: QClient uses discovery + round-robin, but also QClient support to import from qworker.conf the variable WORKERS_LIST that, if exists, can be passed to the QClient initialization `QClient(worker_list=WORKER_LIST)`

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- All 5 modules are tightly coupled (Module 2 imports Module 1, Module 3
  imports Module 1+2, Module 5 tests all), so parallel worktrees would cause
  constant merge conflicts.
- **Cross-feature dependencies**: FEAT-003 (BackgroundService event loop fix)
  must be merged first — it introduced the `execution_mode` parameter that
  this spec extends. **Already merged into `dev`.**

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Jesus Lara | Initial draft |
