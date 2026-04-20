# TASK-020: BackgroundService submit() Passthrough

**Feature**: FEAT-003 — BackgroundService Event Loop Error Fix
**Spec**: `sdd/specs/backgroundservice-eventloop-error.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-019
**Assigned-to**: unassigned

---

## Context

`BackgroundService.submit()` creates `TaskWrapper` instances when raw callables
are passed. It needs to forward the `execution_mode` kwarg so callers can control
whether their task runs in the same loop or a thread.

Implements **Spec Module 2**: BackgroundService submit() passthrough.

---

## Scope

- Modify `BackgroundService.submit()` to extract `execution_mode` from `**kwargs`
  and pass it to the `TaskWrapper` constructor.
- Default to `"same_loop"` when not specified (consistent with TaskWrapper default).
- When `fn` is already a `TaskWrapper`, do NOT override its `execution_mode` —
  the caller already set it at construction time.

**NOT in scope**:
- TaskWrapper changes (TASK-019)
- BackgroundQueue changes (TASK-021)
- Tests (TASK-023)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/service/__init__.py` | MODIFY | Forward `execution_mode` kwarg |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional, Union, Callable  # verified: service/__init__.py:1
import uuid                                    # verified: service/__init__.py:2
from aiohttp import web                        # verified: service/__init__.py:3
from ..queue import BackgroundQueue             # verified: service/__init__.py:4
from ..tracker import JobTracker, RedisJobTracker, JobRecord  # verified: service/__init__.py:5
from ..wrappers import TaskWrapper              # verified: service/__init__.py:6
from ...conf import CACHE_URL                   # verified: service/__init__.py:7
```

### Existing Signatures to Use

```python
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
        self.queue = queue or BackgroundQueue(app, **kwargs)  # line 23
        self.tracker = ...                                     # line 25

    async def submit(
        self,
        fn: Union[Callable, TaskWrapper],
        *args,
        jitter: float = 0.0,
        **kwargs
    ) -> uuid.UUID:  # line 41
        # line 52-53: if isinstance(fn, TaskWrapper): tw = fn
        # line 56-63: else: tw = TaskWrapper(fn, *args, tracker=self.tracker, jitter=jitter, **kwargs)
        # line 64-71: if tw.tracker is None: set tracker and create job
        # line 73: await self.queue.put(tw)
        # line 74: return tw.job_record

# navigator/background/wrappers/__init__.py (after TASK-019)
class TaskWrapper:
    def __init__(
        self,
        fn = None,
        *args,
        execution_mode: str = "same_loop",  # ADDED by TASK-019
        tracker: JobTracker = None,
        jitter: float = 0.0,
        **kwargs
    ):
        self.execution_mode = execution_mode  # ADDED by TASK-019
```

### Does NOT Exist

- ~~`BackgroundService.execution_mode`~~ — not a service-level attribute
- ~~`BackgroundService.execute()`~~ — not a real method; use `submit()`
- ~~`BackgroundService.run_task()`~~ — not a real method
- ~~`BackgroundQueue.submit()`~~ — not a real method; use `put()`

---

## Implementation Notes

### Pattern to Follow

```python
async def submit(
    self,
    fn: Union[Callable, TaskWrapper],
    *args,
    jitter: float = 0.0,
    **kwargs
) -> uuid.UUID:
    if not callable(fn):
        raise ValueError(...)
    
    # Extract execution_mode before passing kwargs to TaskWrapper
    execution_mode = kwargs.pop('execution_mode', 'same_loop')
    
    if isinstance(fn, TaskWrapper):
        tw = fn
        # Do NOT override tw.execution_mode — caller already set it
    else:
        tw = TaskWrapper(
            fn,
            *args,
            execution_mode=execution_mode,
            tracker=self.tracker,
            jitter=jitter,
            **kwargs
        )
    # ... rest unchanged ...
```

### Key Constraints

- Must pop `execution_mode` from `kwargs` BEFORE passing to `TaskWrapper` to
  avoid double-passing (it would appear in both the explicit param and `**kwargs`)
- Actually, `TaskWrapper.__init__` already accepts `execution_mode` as a keyword
  param, so if it's in `**kwargs` it would be captured correctly. But popping
  explicitly is cleaner and allows the `isinstance(fn, TaskWrapper)` branch to
  skip it.

---

## Acceptance Criteria

- [ ] `service.submit(my_coro)` creates TaskWrapper with `execution_mode="same_loop"` by default
- [ ] `service.submit(my_coro, execution_mode="thread")` creates TaskWrapper with thread mode
- [ ] `service.submit(existing_taskwrapper)` does NOT override the wrapper's execution_mode
- [ ] No changes to `submit()` return type (still returns `JobRecord`)

---

## Test Specification

Tests are in TASK-023. Quick manual check:

```python
# After TASK-019 + TASK-020:
service = app['background_service']
job = await service.submit(my_coro_fn)
# job.task_id exists, task runs in same loop
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/backgroundservice-eventloop-error.spec.md`
2. **Check dependencies** — verify TASK-019 is in `tasks/completed/`
3. **Verify the Codebase Contract** — `read navigator/background/service/__init__.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the execution_mode passthrough
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
