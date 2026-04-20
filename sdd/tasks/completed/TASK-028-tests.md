# TASK-028: QWorker Tasker Tests

**Feature**: FEAT-004 — QWorker Background Tasker
**Spec**: `sdd/specs/new-backgroundqueue-tasker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-024, TASK-025, TASK-026, TASK-027
**Assigned-to**: unassigned

---

## Context

Comprehensive test suite for the entire FEAT-004 implementation: QWorkerTasker
class, TaskWrapper remote mode, BackgroundService integration, and package wiring.

Implements **Module 5** from the spec (§3).

---

## Scope

- Create `tests/test_qworker_tasker.py` with:
  - **Unit tests** for `QWorkerTasker` (mocked QClient)
  - **Unit tests** for `TaskWrapper` remote mode (mocked QWorkerTasker)
  - **Integration tests** for `BackgroundService.submit()` with remote mode
  - **Package wiring tests** (import guards)
- All QClient interactions must be mocked — no real qworker instance needed.
- Use `pytest` + `pytest-asyncio` for async tests.
- Use `unittest.mock.AsyncMock` for mocking async methods.

**NOT in scope**: End-to-end tests with a running qworker server.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_qworker_tasker.py` | CREATE | Full test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test dependencies
import pytest                                    # pyproject.toml test extra
from unittest.mock import AsyncMock, MagicMock, patch  # stdlib

# Components under test
from navigator.background.taskers.qworker import QWorkerTasker  # TASK-024
from navigator.background.wrappers import TaskWrapper            # wrappers/__init__.py:52
from navigator.background.service import BackgroundService       # service/__init__.py:13
from navigator.background.tracker import JobTracker, JobRecord   # tracker/__init__.py
from navigator.background.queue import BackgroundQueue           # queue/__init__.py:35
```

### Existing Signatures to Use

```python
# navigator/background/taskers/qworker.py (created by TASK-024)
class QWorkerTasker:
    _VALID_MODES = ("run", "queue", "publish")
    def __init__(self, worker_list=None, timeout=5, default_mode="run"): ...
    async def dispatch(self, fn, *args, remote_mode=None, tracker=None, task_uuid=None, **kwargs): ...
    async def close(self): ...

# navigator/background/wrappers/__init__.py (modified by TASK-025)
VALID_EXECUTION_MODES = ("same_loop", "thread", "remote")  # after TASK-025
class TaskWrapper:
    def __init__(self, fn=None, *args, execution_mode="same_loop",
                 remote_mode="run", worker_list=None, remote_timeout=5, **kwargs): ...
    async def __call__(self): ...

# navigator/background/service/__init__.py (modified by TASK-026)
class BackgroundService:
    async def submit(self, fn, *args, jitter=0.0, **kwargs) -> uuid.UUID: ...
    # accepts execution_mode, remote_mode, worker_list, remote_timeout in kwargs

# navigator/background/tracker/memory.py
class JobTracker:
    async def create_job(self, job, **kwargs) -> JobRecord: ...  # line 71
    async def set_running(self, job_id) -> None: ...             # line 83
    async def set_done(self, job_id, result=None) -> None: ...   # line 89
    async def set_failed(self, job_id, exc) -> None: ...         # line 96
    async def status(self, job_id) -> Optional[JobRecord]: ...   # line 103

# qw/client.py — to be mocked
class QClient:
    def __init__(self, worker_list=None, timeout=5): ...
    async def run(self, fn, *args, use_wrapper=False, **kwargs): ...
    async def queue(self, fn, *args, use_wrapper=True, **kwargs): ...
    async def publish(self, fn, *args, use_wrapper=True, **kwargs): ...
```

### Does NOT Exist

- ~~`QWorkerTasker.run()`~~ — method is `dispatch()`, not `run()`
- ~~`TaskWrapper.remote_dispatch()`~~ — no such method; dispatch happens in `__call__()`
- ~~`BackgroundService.remote_submit()`~~ — use regular `submit()` with `execution_mode="remote"`
- ~~`QClient.status()`~~ — no per-task status method
- ~~`QClient.result()`~~ — no result store

---

## Implementation Notes

### Pattern to Follow

```python
@pytest.fixture
def mock_qclient():
    """Create a mocked QClient."""
    client = MagicMock()
    client.run = AsyncMock(return_value={"answer": 42})
    client.queue = AsyncMock(return_value={"status": "Queued", "task": "fn", "message": "ok"})
    client.publish = AsyncMock(return_value={"status": "Queued", "task": "fn", "message": "stream-1"})
    return client

@pytest.fixture
def tasker(mock_qclient):
    """QWorkerTasker with injected mock QClient."""
    with patch("navigator.background.taskers.qworker.QClient", return_value=mock_qclient):
        from navigator.background.taskers.qworker import QWorkerTasker
        t = QWorkerTasker()
    return t
```

### Key Constraints

- All async tests need `@pytest.mark.asyncio` decorator.
- Mock `qw.client.QClient` at the correct import path:
  `"navigator.background.taskers.qworker.QClient"` (since it's lazy-imported).
- For testing the missing-dep scenario, use `monkeypatch` to make the import fail.
- For BackgroundService integration tests, create a real `web.Application` with
  mocked queue and tracker.

### Test Matrix

| Test | Mode | What to Verify |
|---|---|---|
| `test_dispatch_run` | run | QClient.run() called, result returned, tracker → done |
| `test_dispatch_queue` | queue | QClient.queue() called, tracker → queued_remote |
| `test_dispatch_publish` | publish | QClient.publish() called, tracker → queued_remote |
| `test_dispatch_run_error` | run | Exception from QClient.run(), tracker → failed |
| `test_dispatch_invalid_mode` | bad | ValueError raised |
| `test_taskwrapper_remote` | run | TaskWrapper.__call__() delegates to QWorkerTasker |
| `test_taskwrapper_same_loop_unaffected` | - | Existing modes still work |
| `test_submit_remote` | run | BackgroundService.submit() end-to-end |
| `test_import_without_qworker` | - | ImportError with helpful message |
| `test_package_export` | - | QWorkerTasker accessible from navigator.background |

---

## Acceptance Criteria

- [ ] `tests/test_qworker_tasker.py` exists with ≥10 tests
- [ ] All tests pass: `pytest tests/test_qworker_tasker.py -v`
- [ ] QWorkerTasker tested with all three modes (run, queue, publish)
- [ ] Error paths tested (exception from QClient, missing dep)
- [ ] TaskWrapper remote mode tested
- [ ] BackgroundService integration tested
- [ ] Existing execution modes (same_loop, thread) not broken

---

## Test Specification

```python
# tests/test_qworker_tasker.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── QWorkerTasker Unit Tests ─────────────────────────────────────

class TestQWorkerTaskerInit:
    def test_creates_with_defaults(self):
        """Default worker_list=None, timeout=5, default_mode='run'."""

    def test_creates_with_custom_workers(self):
        """Accepts custom worker_list."""

    def test_missing_qworker_raises(self):
        """ImportError with install instructions when qw missing."""

    def test_invalid_default_mode(self):
        """ValueError for bogus default_mode."""


class TestQWorkerTaskerDispatch:
    @pytest.mark.asyncio
    async def test_run_mode(self, tasker, mock_qclient):
        """run mode calls QClient.run() and returns result."""

    @pytest.mark.asyncio
    async def test_queue_mode(self, tasker, mock_qclient):
        """queue mode calls QClient.queue()."""

    @pytest.mark.asyncio
    async def test_publish_mode(self, tasker, mock_qclient):
        """publish mode calls QClient.publish()."""

    @pytest.mark.asyncio
    async def test_run_exception_updates_tracker(self, tasker, mock_qclient):
        """Exception from QClient.run() sets tracker to failed."""

    @pytest.mark.asyncio
    async def test_invalid_mode(self, tasker):
        """ValueError for unknown remote_mode."""


# ── TaskWrapper Remote Mode Tests ────────────────────────────────

class TestTaskWrapperRemote:
    def test_accepts_remote_mode(self):
        """TaskWrapper(execution_mode='remote') is valid."""

    @pytest.mark.asyncio
    async def test_calls_qworker_tasker(self):
        """__call__() with remote mode delegates to QWorkerTasker."""

    def test_same_loop_unaffected(self):
        """same_loop mode still works after remote addition."""

    def test_thread_unaffected(self):
        """thread mode still works after remote addition."""


# ── BackgroundService Integration Tests ──────────────────────────

class TestBackgroundServiceRemote:
    @pytest.mark.asyncio
    async def test_submit_remote_run(self):
        """submit() with execution_mode='remote', remote_mode='run' works."""

    @pytest.mark.asyncio
    async def test_submit_remote_queue(self):
        """submit() with execution_mode='remote', remote_mode='queue' works."""


# ── Package Wiring Tests ────────────────────────────────────────

class TestPackageWiring:
    def test_import_background_clean(self):
        """navigator.background imports without qworker installed."""

    def test_qworkertasker_accessible(self):
        """QWorkerTasker available from navigator.background."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/new-backgroundqueue-tasker.spec.md`
2. **Check dependencies** — ALL prior tasks (TASK-024 through TASK-027) must be completed
3. **Verify the Codebase Contract** — implementations from TASK-024..027 may have
   deviated from plan; read the actual code before writing tests
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Write tests** — run `pytest tests/test_qworker_tasker.py -v` iteratively
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

Created `tests/test_qworker_tasker.py` with **31 tests** across 5 groups:

- `TestQWorkerTaskerInit` (4): defaults, custom workers, invalid default
  mode, missing-qworker ImportError.
- `TestQWorkerTaskerDispatch` (6): all three modes (run/queue/publish),
  `use_wrapper` contract, fallback to default_mode, invalid mode, exception
  propagation.
- `TestQWorkerTaskerTracker` (6): run→done, queue→queued_remote,
  publish→queued_remote, exception→failed, no-tracker noop,
  close() is a noop.
- `TestTaskWrapperRemote` (9): VALID_EXECUTION_MODES, construction,
  kwarg-stripping, same_loop/thread untouched, run/queue/publish dispatch
  via `QWorkerTasker`, exception path returns `{"status": "failed"}`.
- `TestBackgroundServiceRemote` (2): end-to-end `/remote` submit forwards
  `remote_mode` / `worker_list` / `remote_timeout` to a mocked
  `QWorkerTasker`; plain `submit()` still defaults to `same_loop` and
  executes locally.
- `TestPackageWiring` (4): `import navigator.background` is clean,
  `QWorkerTasker` re-exports, `__all__`.

### Testing strategy

Because the real `qw.client` module has a broken transitive import chain
(via `flowtask`) in the minimal test environment, we inject a fake
`qw.client` module into `sys.modules` before construction. This exercises
the real lazy-import code path inside `QWorkerTasker.__init__` while
keeping the test suite hermetic.

### Results

```
tests/test_qworker_tasker.py ............................... 31 passed
tests/test_background_service.py ......                        7 passed
=============================================================
                                                              38 passed
```

No regressions in the pre-existing background service tests.

**Verified at commit:** `4da7e77`
