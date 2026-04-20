# TASK-025: TaskWrapper Remote Execution Mode

**Feature**: FEAT-004 — QWorker Background Tasker
**Spec**: `sdd/specs/new-backgroundqueue-tasker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-024
**Assigned-to**: unassigned

---

## Context

Extends `TaskWrapper` to support `execution_mode="remote"`, delegating task
execution to `QWorkerTasker` instead of running locally.

Implements **Module 2** from the spec (§3).

---

## Scope

- Add `"remote"` to `VALID_EXECUTION_MODES` tuple (line 14 of `wrappers/__init__.py`).
- Accept new kwargs in `TaskWrapper.__init__()`:
  - `remote_mode` (str, default `"run"`) — which QClient method to use.
  - `worker_list` (list[tuple[str,int]] | None, default None) — worker addresses.
  - `remote_timeout` (int, default 5) — QClient timeout.
  Store these as instance attributes.
- Add a new branch in `TaskWrapper.__call__()` for `execution_mode == "remote"`:
  1. Lazy-create a `QWorkerTasker` instance (cached on the class or instance).
  2. Call `await tasker.dispatch(self.fn, *self.args, remote_mode=self.remote_mode, tracker=self.tracker, task_uuid=self.task_uuid, **self.kwargs)`.
  3. For `run` mode: return `{"status": "done", "result": result}`.
  4. For `queue`/`publish` modes: return `{"status": "queued_remote", "result": response}`.
  5. On exception: return `{"status": "failed", "error": str(exc)}` and update tracker.
- If `execution_mode == "remote"` but `qw` is not installed, the error surfaces
  when `QWorkerTasker()` is constructed (at call time, not at TaskWrapper init).

**NOT in scope**: Modifying BackgroundService (TASK-026). Modifying pyproject.toml (TASK-027).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/wrappers/__init__.py` | MODIFY | Add "remote" mode + dispatch logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in wrappers/__init__.py
from typing import Callable, Coroutine, Any, Union, Optional, Awaitable  # line 1
import uuid       # line 3
import logging     # line 4
import asyncio     # line 6
from ..tracker import JobTracker, JobRecord  # line 8

# New import needed (lazy, inside __call__)
# from ..taskers.qworker import QWorkerTasker  # created by TASK-024
```

### Existing Signatures to Use

```python
# navigator/background/wrappers/__init__.py
VALID_EXECUTION_MODES = ("same_loop", "thread")  # line 14

class TaskWrapper:  # line 52
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,
        *args,
        execution_mode: str = "same_loop",   # line 76
        tracker: JobTracker = None,           # line 77
        jitter: float = 0.0,                  # line 78
        logger: Optional[logging.Logger] = None,  # line 79
        max_retries: int = 0,                 # line 80
        retry_delay: float = 0.0,             # line 81
        **kwargs
    ): ...
        # kwargs.pop pattern used for: name (line 92), callback (line 93),
        # status (line 94), content (line 103)
        # remaining kwargs stored in self.kwargs (line 123)

    @property
    def task_uuid(self) -> uuid.UUID: ...     # line 125

    async def __call__(self):                 # line 165
        # Line 201: if self.execution_mode == "same_loop":
        # Line 235: else: (thread mode)
        # NEW: add elif self.execution_mode == "remote": before else

# navigator/background/taskers/qworker.py (created by TASK-024)
class QWorkerTasker:
    def __init__(self, worker_list=None, timeout=5, default_mode="run"): ...
    async def dispatch(self, fn, *args, remote_mode=None, tracker=None, task_uuid=None, **kwargs): ...
```

### Does NOT Exist

- ~~`TaskWrapper.remote_mode`~~ — does not exist yet (this task adds it)
- ~~`TaskWrapper.worker_list`~~ — does not exist yet (this task adds it)
- ~~`TaskWrapper._tasker`~~ — does not exist yet (this task adds it)
- ~~`VALID_EXECUTION_MODES` containing `"remote"`~~ — currently only `("same_loop", "thread")`

---

## Implementation Notes

### Pattern to Follow

In `__init__()`, extract the new kwargs after `retry_delay`:
```python
# Remote execution params (only used when execution_mode == "remote")
self.remote_mode: str = kwargs.pop('remote_mode', 'run')
self.worker_list = kwargs.pop('worker_list', None)
self.remote_timeout: int = kwargs.pop('remote_timeout', 5)
self._tasker = None  # lazy-created QWorkerTasker
```

In `__call__()`, add a new branch BETWEEN the `same_loop` and `thread` blocks:
```python
elif self.execution_mode == "remote":
    try:
        if self._tasker is None:
            from ..taskers.qworker import QWorkerTasker
            self._tasker = QWorkerTasker(
                worker_list=self.worker_list,
                timeout=self.remote_timeout,
                default_mode=self.remote_mode,
            )
        result = await self._tasker.dispatch(
            self.fn, *self.args,
            remote_mode=self.remote_mode,
            tracker=self.tracker,
            task_uuid=self.task_uuid,
            **self.kwargs
        )
        # ... handle result based on mode ...
    except Exception as exc:
        # ... set tracker to failed, return error dict ...
```

### Key Constraints

- `VALID_EXECUTION_MODES` must be updated to `("same_loop", "thread", "remote")`.
- The `QWorkerTasker` import is lazy (inside `__call__`) so that TaskWrapper
  remains importable without qworker installed.
- The `_tasker` instance is cached per-TaskWrapper instance, not per-class.

---

## Acceptance Criteria

- [ ] `VALID_EXECUTION_MODES` includes `"remote"`
- [ ] `TaskWrapper(fn, execution_mode="remote")` does NOT raise at construction
- [ ] `await task()` with `execution_mode="remote"` calls `QWorkerTasker.dispatch()`
- [ ] `run` mode returns `{"status": "done", "result": ...}`
- [ ] `queue`/`publish` modes return `{"status": "queued_remote", "result": ...}`
- [ ] Exception from dispatch returns `{"status": "failed", "error": ...}`
- [ ] Existing `same_loop` and `thread` modes are NOT affected

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from navigator.background.wrappers import TaskWrapper


class TestTaskWrapperRemoteMode:
    def test_valid_execution_modes(self):
        """'remote' is now accepted."""
        tw = TaskWrapper(lambda: None, execution_mode="remote")
        assert tw.execution_mode == "remote"

    @pytest.mark.asyncio
    async def test_remote_dispatches_to_qworker(self):
        """Remote mode delegates to QWorkerTasker.dispatch()."""
        # ... mock QWorkerTasker ...

    def test_existing_modes_unaffected(self):
        """same_loop and thread still work."""
        tw1 = TaskWrapper(lambda: None, execution_mode="same_loop")
        tw2 = TaskWrapper(lambda: None, execution_mode="thread")
        assert tw1.execution_mode == "same_loop"
        assert tw2.execution_mode == "thread"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/new-backgroundqueue-tasker.spec.md`
2. **Check dependencies** — TASK-024 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — re-read `wrappers/__init__.py` line numbers
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the changes to TaskWrapper
6. **Run existing tests** to verify no regressions in same_loop/thread modes
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
