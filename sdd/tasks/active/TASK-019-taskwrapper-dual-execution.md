# TASK-019: TaskWrapper Dual Execution Mode

**Feature**: FEAT-003 — BackgroundService Event Loop Error Fix
**Spec**: `sdd/specs/backgroundservice-eventloop-error.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core fix for the "attached to a different loop" bug. The current
`TaskWrapper.__call__()` always delegates to `coroutine_in_thread()`, which
creates a new event loop in a new thread. When the user's coroutine shares
application state (LLM client sessions, DB pools, asyncio Locks), those objects
are bound to the main event loop and fail in the thread's loop.

Implements **Spec Module 1**: TaskWrapper Dual Execution Mode.

---

## Scope

- Add `execution_mode: str` parameter to `TaskWrapper.__init__()` with default `"same_loop"`.
  Valid values: `"same_loop"`, `"thread"`. Raise `ValueError` for anything else.
- Rewrite `TaskWrapper.__call__()` to branch on `execution_mode`:
  - **`"same_loop"`**: Use `asyncio.create_task(self.fn(*args, **kwargs))` to schedule
    the coroutine on the running event loop. `await` the task. On success, call
    `_finish(result, None)` directly. On exception, call `_finish(None, exc)`.
    Call `_wrapped_callback(result, exc, loop=asyncio.get_running_loop())` if user
    callback exists. Return `{"status": "done", "result": result}` or
    `{"status": "failed", "error": str(exc)}`.
  - **`"thread"`**: Preserve the existing `coroutine_in_thread()` path exactly as-is
    (fire-and-forget, returns `{"status": "running"}` immediately).
- Remove the unused `ThreadPoolExecutor(max_workers=1)` context manager wrapping
  `coroutine_in_thread()` in `__call__()` (line 189) — the executor is never used.
- Keep `coroutine_in_thread()` function unchanged.

**NOT in scope**:
- Changes to `BackgroundService.submit()` (TASK-020)
- Changes to `BackgroundQueue._execute_taskwrapper()` (TASK-021)
- Changes to `BaseHandler._loop` (TASK-022)
- Tests (TASK-023)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/wrappers/__init__.py` | MODIFY | Add `execution_mode` param, dual-path `__call__()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Callable, Coroutine, Any, Union, Optional, Awaitable  # verified: wrappers/__init__.py:1
import uuid          # verified: wrappers/__init__.py:2
import logging       # verified: wrappers/__init__.py:3
import threading     # verified: wrappers/__init__.py:4
import random        # verified: wrappers/__init__.py:5
import asyncio       # verified: wrappers/__init__.py:6
from concurrent.futures import ThreadPoolExecutor  # verified: wrappers/__init__.py:7
from ..tracker import JobTracker, JobRecord  # verified: wrappers/__init__.py:8
```

### Existing Signatures to Use

```python
# navigator/background/wrappers/__init__.py

# line 11
coroutine = Callable[[int], Coroutine[Any, Any, str]]
# line 12
OnCompleteFn = Callable[[Any, Optional[Exception]], Awaitable[None]]

# line 15-47 — DO NOT MODIFY this function
def coroutine_in_thread(
    coro: coroutine,
    callback: Optional[coroutine] = None,
    on_complete: OnCompleteFn = None,
) -> threading.Event:
    parent_loop = asyncio.get_running_loop()  # line 21
    # ... creates thread, new_loop, runs coro ...

# line 50-213 — class to MODIFY
class TaskWrapper:
    def __init__(
        self,
        fn: Union[Callable, coroutine] = None,  # line 57
        *args,
        tracker: JobTracker = None,              # line 59
        jitter: float = 0.0,                     # line 60
        logger: Optional[logging.Logger] = None, # line 61
        max_retries: int = 0,                    # line 62
        retry_delay: float = 0.0,                # line 63
        **kwargs
    ):
        self.fn = fn                             # line 66
        self.tracker = tracker                   # line 67
        self._name: str                          # line 68
        self._user_callback                      # line 69
        self.jitter: float                       # line 76
        self.job_record: JobRecord               # line 84
        self.args = args                         # line 98
        self.kwargs = kwargs                     # line 99
        self.max_retries = max_retries           # line 94
        self.retries_done = 0                    # line 95
        self.retry_delay = retry_delay           # line 96

    @property
    def task_uuid(self) -> uuid.UUID:            # line 101
        return self.job_record.task_id

    def add_callback(self, callback):            # line 108

    async def _wrapped_callback(self, result, exc, loop):  # line 119
        # Calls self._user_callback(result, exc, loop=loop,
        #   job_record=self.job_record, task_id=self.job_record.task_id)

    async def __call__(self):                    # line 140
        # Current: always calls coroutine_in_thread() at line 193
        # Wraps in ThreadPoolExecutor(max_workers=1) at line 189 — UNUSED
```

### Does NOT Exist

- ~~`TaskWrapper.execution_mode`~~ — does not exist yet, you are adding it
- ~~`TaskWrapper.run_in_loop()`~~ — not a real method
- ~~`TaskWrapper._execute_same_loop()`~~ — not a real method, do not invent helpers
- ~~`coroutine_in_thread.parent_loop`~~ — local variable, not accessible
- ~~`JobRecord.loop`~~ — JobRecord has no event loop field

---

## Implementation Notes

### Pattern to Follow

The `same_loop` path should follow this structure inside `__call__()`:

```python
async def __call__(self):
    # ... tracker.set_running() and jitter delay (keep existing) ...
    
    if self.execution_mode == "same_loop":
        try:
            coro = self.fn(*self.args, **self.kwargs)
            result = await asyncio.create_task(coro)
            # success path: update tracker, call callback
            if self._user_callback:
                await self._wrapped_callback(
                    result, None, loop=asyncio.get_running_loop()
                )
            if self.tracker:
                await self.tracker.set_done(self.task_uuid, result)
            return {"status": "done", "result": result}
        except Exception as exc:
            # failure path
            if self._user_callback:
                await self._wrapped_callback(
                    None, exc, loop=asyncio.get_running_loop()
                )
            if self.tracker:
                await self.tracker.set_failed(self.task_uuid, exc)
            return {"status": "failed", "error": str(exc)}
    else:
        # thread mode — existing behavior, minus unused ThreadPoolExecutor
        coro = self.fn(*self.args, **self.kwargs)
        callback_to_use = self._wrapped_callback if self._user_callback else None
        coroutine_in_thread(coro, callback_to_use, on_complete=_finish)
        return {"status": "running"}
```

### Key Constraints

- `execution_mode` must be validated in `__init__()` — raise `ValueError` for invalid values
- The `_finish()` closure is only needed for thread mode (it uses `run_coroutine_threadsafe`)
- In same-loop mode, tracker updates and callbacks happen inline, no need for `_finish()`
- Keep `CancelledError` handling for both modes
- Do NOT modify `coroutine_in_thread()` — it stays as-is

---

## Acceptance Criteria

- [ ] `TaskWrapper("same_loop")` creates tasks on the running event loop
- [ ] `TaskWrapper("thread")` preserves existing `coroutine_in_thread` behavior
- [ ] Default `execution_mode` is `"same_loop"`
- [ ] Invalid `execution_mode` raises `ValueError`
- [ ] Unused `ThreadPoolExecutor(max_workers=1)` removed from `__call__()`
- [ ] Tracker transitions: pending → running → done (or failed) in same-loop mode
- [ ] User callbacks receive `loop=asyncio.get_running_loop()` in same-loop mode
- [ ] No import changes to `navigator/background/__init__.py`

---

## Test Specification

Tests are in TASK-023. For manual verification during development:

```python
import asyncio
from navigator.background.wrappers import TaskWrapper
from navigator.background.tracker.memory import JobTracker

async def test_same_loop():
    tracker = JobTracker()
    lock = asyncio.Lock()  # shared with main loop
    
    async def task_using_shared_lock():
        async with lock:
            return "ok"
    
    tw = TaskWrapper(fn=task_using_shared_lock, tracker=tracker)
    assert tw.execution_mode == "same_loop"
    result = await tw()
    assert result["status"] == "done"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/backgroundservice-eventloop-error.spec.md`
2. **Check dependencies** — none, this is the first task
3. **Verify the Codebase Contract** — `read navigator/background/wrappers/__init__.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the dual execution mode in `TaskWrapper`
6. **Verify** by running: `python -c "from navigator.background.wrappers import TaskWrapper; tw = TaskWrapper(fn=lambda: None); print(tw.execution_mode)"`
7. **Move this file** to `tasks/completed/TASK-019-taskwrapper-dual-execution.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
