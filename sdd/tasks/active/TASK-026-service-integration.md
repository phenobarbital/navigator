# TASK-026: BackgroundService Remote Integration

**Feature**: FEAT-004 — QWorker Background Tasker
**Spec**: `sdd/specs/new-backgroundqueue-tasker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-024, TASK-025
**Assigned-to**: unassigned

---

## Context

Wires `BackgroundService.submit()` to forward remote-related kwargs
(`remote_mode`, `worker_list`, `remote_timeout`) to `TaskWrapper`. Also caches
a shared `QWorkerTasker` instance on the service for reuse across requests.

Implements **Module 3** from the spec (§3).

---

## Scope

- Modify `BackgroundService.submit()` to extract `remote_mode`, `worker_list`,
  and `remote_timeout` from `**kwargs` (alongside the existing `execution_mode`
  extraction at line 81) and forward them to the `TaskWrapper` constructor.
- Add a `_qworker_tasker` attribute (initially `None`) to `BackgroundService.__init__()`.
- When `execution_mode == "remote"`, create/cache a `QWorkerTasker` on
  `self._qworker_tasker` and inject it into the TaskWrapper via a new
  `tasker` kwarg (so each TaskWrapper doesn't recreate the client).
  Alternatively, just let TaskWrapper lazy-create it — simpler, since QClient
  creates per-call connections anyway. **Prefer the simpler approach.**
- Ensure that `submit()` docstring is updated to document the new kwargs.

**NOT in scope**: Modifying pyproject.toml (TASK-027). Writing tests (TASK-028).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/service/__init__.py` | MODIFY | Forward remote kwargs in submit() |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator/background/service/__init__.py — existing imports
from typing import Optional, Union, Callable  # line 1
import uuid                                    # line 2
from aiohttp import web                        # line 3
from ..queue import BackgroundQueue            # line 4
from ..tracker import JobTracker, RedisJobTracker, JobRecord  # line 5
from ..wrappers import TaskWrapper             # line 6
from ...conf import CACHE_URL                  # line 7
```

### Existing Signatures to Use

```python
# navigator/background/service/__init__.py
class BackgroundService:                       # line 13
    def __init__(
        self,
        app: web.Application,
        queue: Optional[BackgroundQueue] = None,
        tracker: Optional[JobTracker] = None,
        tracker_type: str = 'memory',          # line 23
        **kwargs
    ) -> None: ...                             # line 25

    async def submit(
        self,
        fn: Union[Callable, TaskWrapper],
        *args,
        jitter: float = 0.0,
        **kwargs
    ) -> uuid.UUID: ...                        # line 54
        # Line 81: execution_mode = kwargs.pop('execution_mode', 'same_loop')
        # Line 83-86: if isinstance(fn, TaskWrapper): tw = fn
        # Line 88-96: else: tw = TaskWrapper(fn, *args, execution_mode=..., **kwargs)
        # Line 97-99: tracker assignment
        # Line 100-101: create job record
        # Line 104: await self.queue.put(tw)
        # Line 105: return tw.job_record

# navigator/background/wrappers/__init__.py (after TASK-025)
class TaskWrapper:                             # line 52
    def __init__(
        self,
        fn=None, *args,
        execution_mode="same_loop",
        # ... existing params ...
        remote_mode="run",        # added by TASK-025
        worker_list=None,         # added by TASK-025
        remote_timeout=5,         # added by TASK-025
        **kwargs
    ): ...
```

### Does NOT Exist

- ~~`BackgroundService._qworker_tasker`~~ — does not exist yet
- ~~`BackgroundService.remote_submit()`~~ — no such method; use `submit()` with `execution_mode="remote"`
- ~~`BackgroundService.tasker`~~ — no such attribute

---

## Implementation Notes

### Pattern to Follow

In `submit()`, after line 81 (`execution_mode = kwargs.pop(...)`), extract the
remote kwargs:

```python
execution_mode = kwargs.pop('execution_mode', 'same_loop')
remote_mode = kwargs.pop('remote_mode', 'run')
worker_list = kwargs.pop('worker_list', None)
remote_timeout = kwargs.pop('remote_timeout', 5)
```

Then forward them when creating the TaskWrapper (lines 89-96):

```python
tw = TaskWrapper(
    fn,
    *args,
    execution_mode=execution_mode,
    tracker=self.tracker,
    jitter=jitter,
    remote_mode=remote_mode,
    worker_list=worker_list,
    remote_timeout=remote_timeout,
    **kwargs
)
```

### Key Constraints

- These kwargs MUST be popped before `**kwargs` is forwarded to TaskWrapper
  to avoid duplicate argument errors.
- The docstring should list `remote_mode`, `worker_list`, `remote_timeout` as
  optional params for remote dispatch.

---

## Acceptance Criteria

- [ ] `BackgroundService.submit(fn, execution_mode="remote", remote_mode="run")` works
- [ ] `remote_mode`, `worker_list`, `remote_timeout` are extracted and forwarded
- [ ] Existing calls without remote kwargs still work (no regressions)
- [ ] Docstring updated

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


class TestBackgroundServiceRemote:
    @pytest.mark.asyncio
    async def test_submit_remote_forwards_kwargs(self):
        """submit() with remote kwargs creates TaskWrapper with remote params."""
        # ... create BackgroundService with mocked queue/tracker ...
        # ... call submit(fn, execution_mode="remote", remote_mode="publish") ...
        # ... assert TaskWrapper was created with remote_mode="publish" ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/new-backgroundqueue-tasker.spec.md`
2. **Check dependencies** — TASK-024 and TASK-025 must be completed
3. **Verify the Codebase Contract** — re-read `service/__init__.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the submit() changes
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
