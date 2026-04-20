# TASK-021: BackgroundQueue Cleanup

**Feature**: FEAT-003 — BackgroundService Event Loop Error Fix
**Spec**: `sdd/specs/backgroundservice-eventloop-error.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-019
**Assigned-to**: unassigned

---

## Context

`BackgroundQueue._execute_taskwrapper()` wraps the `await task()` call in a
`ThreadPoolExecutor(max_workers=1)` context manager that is never actually used.
The executor is created and destroyed on every task execution, wasting resources.
This task cleans it up.

Implements **Spec Module 3**: BackgroundQueue cleanup.

---

## Scope

- Remove the `with ThreadPoolExecutor(max_workers=1) as executor:` wrapper in
  `_execute_taskwrapper()` (line 181). The `await task()` call should remain
  at the same indentation level, inside the existing try/except.
- Ensure both `same_loop` and `thread` execution modes work correctly from
  the queue consumer's perspective:
  - `same_loop`: `await task()` returns `{"status": "done", ...}` or
    `{"status": "failed", ...}` — consumer gets the final result.
  - `thread`: `await task()` returns `{"status": "running"}` immediately —
    consumer moves on, actual completion happens via callback in background.

**NOT in scope**:
- TaskWrapper changes (TASK-019)
- BackgroundService changes (TASK-020)
- Modifying `_execute_coroutine()` or `_execute_callable()`
- Tests (TASK-023)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/queue/__init__.py` | MODIFY | Remove unused ThreadPoolExecutor in `_execute_taskwrapper()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import random                                          # verified: queue/__init__.py:1
from typing import Union, Optional, Any                # verified: queue/__init__.py:2-6
import sys, uuid                                       # verified: queue/__init__.py:7-8
from collections.abc import Awaitable, Callable, Coroutine  # verified: queue/__init__.py:9
import contextlib                                      # verified: queue/__init__.py:10
from functools import partial                          # verified: queue/__init__.py:11
from concurrent.futures import ThreadPoolExecutor      # verified: queue/__init__.py:12
from importlib import import_module                    # verified: queue/__init__.py:13
import asyncio, time                                   # verified: queue/__init__.py:14-15
import psutil                                          # verified: queue/__init__.py:16
from aiohttp import web                                # verified: queue/__init__.py:17
from navconfig.logging import logging                  # verified: queue/__init__.py:18
from ...conf import QUEUE_CALLBACK                     # verified: queue/__init__.py:19
from ..wrappers import TaskWrapper, coroutine_in_thread  # verified: queue/__init__.py:20
```

### Existing Signatures to Use

```python
# navigator/background/queue/__init__.py

class BackgroundQueue:  # line 35
    # ... __init__ at line 47 ...
    
    async def _execute_taskwrapper(self, task: TaskWrapper):  # line 178
        """Execute the a task as a TaskWrapper."""
        result = None
        with ThreadPoolExecutor(max_workers=1) as executor:  # line 181 ← REMOVE THIS
            try:
                result = await task()                         # line 183 ← KEEP
            except asyncio.CancelledError:                    # line 184
                # ... lines 185-190 ...
            except Exception as e:                            # line 191
                # ... lines 192-209 ...
        return result                                         # line 210

    async def process_queue(self):                            # line 257
        # ... main consumer loop ...
        # line 280-281: if isinstance(task, TaskWrapper): result = await self._execute_taskwrapper(task)
```

### Does NOT Exist

- ~~`BackgroundQueue.run_task()`~~ — not a real method
- ~~`BackgroundQueue.submit()`~~ — not a real method; use `put()`
- ~~`BackgroundQueue._execute_in_thread()`~~ — not a real method
- ~~`_execute_taskwrapper` `executor` parameter~~ — executor is unused local

---

## Implementation Notes

### Before (current code, lines 178-210):

```python
async def _execute_taskwrapper(self, task: TaskWrapper):
    result = None
    with ThreadPoolExecutor(max_workers=1) as executor:  # REMOVE
        try:
            result = await task()
        except asyncio.CancelledError:
            ...
        except Exception as e:
            ...
    return result
```

### After:

```python
async def _execute_taskwrapper(self, task: TaskWrapper):
    result = None
    try:
        result = await task()
    except asyncio.CancelledError:
        ...
    except Exception as e:
        ...
    return result
```

### Key Constraints

- Only remove the `with ThreadPoolExecutor(...)` wrapper — keep ALL exception
  handling logic intact
- The `executor` variable in the `with` block is never referenced anywhere in
  the method body — confirm this before removing
- `ThreadPoolExecutor` import can remain (used elsewhere in the file by
  `_execute_callable` and `BackgroundTask.run`)

---

## Acceptance Criteria

- [ ] `_execute_taskwrapper()` no longer creates a `ThreadPoolExecutor`
- [ ] `await task()` still correctly returns result dict in both modes
- [ ] Exception handling (CancelledError, general Exception) preserved
- [ ] `tracker.set_failed()` still called on exception
- [ ] Existing `process_queue()` consumer flow unchanged

---

## Test Specification

Tests are in TASK-023. No isolated test needed for this cleanup — it's verified
by the end-to-end tests.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/backgroundservice-eventloop-error.spec.md`
2. **Check dependencies** — verify TASK-019 is in `tasks/completed/`
3. **Verify the Codebase Contract** — `read navigator/background/queue/__init__.py`
4. **Confirm** `executor` variable is unused in `_execute_taskwrapper` body
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the cleanup (remove `with` wrapper, dedent body)
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
