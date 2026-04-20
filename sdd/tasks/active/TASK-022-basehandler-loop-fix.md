# TASK-022: BaseHandler Event Loop Fix

**Feature**: FEAT-003 — BackgroundService Event Loop Error Fix
**Spec**: `sdd/specs/backgroundservice-eventloop-error.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`BaseHandler.__init__()` uses the deprecated `asyncio.get_event_loop()` to store
`self._loop`. In Python 3.10+, this can return a different loop than the one
actually running, or raise a DeprecationWarning. Since `BaseHandler` is the parent
of `BaseView`, which is the parent of all view handlers including `AgentHandler`,
a stale loop reference here contributes to event loop confusion.

Implements **Spec Module 4**: BaseHandler event loop fix.

This task is **independent** of Modules 1-3 and can be implemented in parallel.

---

## Scope

- Replace the eager `self._loop = asyncio.get_event_loop()` assignment at line 51
  of `navigator/views/base.py` with a lazy property that calls
  `asyncio.get_running_loop()` when accessed from an async context.
- The property must NOT break synchronous code that accesses `self._loop` before
  an event loop is running — return `None` or fall back gracefully.
- Verify no other code in `base.py` depends on `self._loop` being set at `__init__`
  time.

**NOT in scope**:
- Fixing `self._loop` in `navigator/navigator.py` (different class, different purpose)
- Fixing `self._loop` in `navigator/handlers/base.pyx` (Cython handler, separate concern)
- Changes to `navigator/applications/base.pyx`
- Tests for background service (TASK-023)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/views/base.py` | MODIFY | Replace `self._loop` eager assignment with lazy property |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio  # verified: views/base.py:1
from typing import Any, Dict, Optional, Union, Tuple, List  # verified: views/base.py:2
from collections.abc import Callable  # verified: views/base.py:3
from abc import ABC  # verified: views/base.py:4
```

### Existing Signatures to Use

```python
# navigator/views/base.py

class BaseHandler(ABC):  # line 42
    _logger_name: str = "navigator"    # line 43
    _lasterr = None                    # line 44
    _allowed = [...]                   # line 45
    _allowed_methods = [...]           # line 46

    def __init__(self, *args, **kwargs):  # line 48
        super().__init__(*args, **kwargs)
        self._config = None                                          # line 50
        self._loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()  # line 51 ← FIX THIS
        self._json: Callable = JSONContent()                         # line 52
        self.logger: logging.Logger = None                           # line 53
        self.post_init(self, *args, **kwargs)                        # line 54

    def post_init(self, *args, **kwargs):  # line 56
    def log(self, message: str):           # line 60
    def log_error(self, message: str):     # line 63
    async def session(self):               # line 66

# Usage of self._loop in this file (searched via grep):
# ONLY line 51 assigns it. No other references in base.py.
# Other files that reference self._loop:
#   navigator/navigator.py — different class (AppRunner), NOT BaseHandler
#   navigator/handlers/base.pyx — Cython BaseAppHandler, NOT BaseHandler
#   navigator/applications/base.pyx — BaseApplication, NOT BaseHandler
```

### Does NOT Exist

- ~~`BaseHandler.get_loop()`~~ — not a method
- ~~`BaseHandler.loop` (as property)~~ — does not exist yet, you are adding it
- ~~`BaseHandler._event_loop`~~ — not an attribute
- ~~`BaseView._loop`~~ — BaseView inherits from BaseHandler, does not override `_loop`

---

## Implementation Notes

### Pattern to Follow

Replace the eager assignment with a private backing field + property:

```python
class BaseHandler(ABC):
    # ...
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config = None
        self.__loop: Optional[asyncio.AbstractEventLoop] = None  # lazy
        self._json: Callable = JSONContent()
        self.logger: logging.Logger = None
        self.post_init(self, *args, **kwargs)

    @property
    def _loop(self) -> Optional[asyncio.AbstractEventLoop]:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return self.__loop
    
    @_loop.setter
    def _loop(self, value: asyncio.AbstractEventLoop):
        self.__loop = value
```

### Key Constraints

- **Must keep `_loop` as the public name** — downstream code (including
  `navigator.py` subclasses) may access `self._loop` directly.
- The property approach lets existing code like `self._loop = some_loop` still
  work (via the setter), while reads prefer the running loop.
- `navigator/navigator.py` has its own `_loop` assignment (`self._loop = asyncio.get_event_loop()`)
  but that's in `AppRunner.__init__()`, a completely different class. Do NOT touch it.
- The getter `try/except RuntimeError` handles the case where `_loop` is accessed
  outside of an async context (e.g., during startup before the loop is running).

---

## Acceptance Criteria

- [ ] `self._loop` returns `asyncio.get_running_loop()` when called from async context
- [ ] `self._loop` returns the stored fallback when no loop is running
- [ ] `self._loop = some_loop` still works (setter)
- [ ] No `DeprecationWarning` from `asyncio.get_event_loop()` in BaseHandler
- [ ] `BaseView` subclasses (including `AgentHandler`) work without changes

---

## Test Specification

```python
import asyncio
import pytest
from navigator.views.base import BaseHandler

class ConcreteHandler(BaseHandler):
    """Minimal concrete subclass for testing."""
    pass

@pytest.mark.asyncio
async def test_basehandler_loop_returns_running_loop():
    loop = asyncio.get_running_loop()
    # BaseHandler can't be instantiated directly (ABC), use concrete
    # But we can test the property logic
    handler = ConcreteHandler.__new__(ConcreteHandler)
    handler._BaseHandler__loop = None
    assert handler._loop is loop
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/backgroundservice-eventloop-error.spec.md`
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — `read navigator/views/base.py` lines 42-55
4. **Grep for `self._loop`** in `navigator/views/base.py` to confirm no other usages
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the lazy property
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
