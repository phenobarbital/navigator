# TASK-002: Cython Cleanup — Convert Exceptions and Remove Dead Cython Code

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

After TASK-001 benchmarks, this task converts Cython modules with no performance benefit to pure Python. At minimum: `exceptions/exceptions.pyx` and `utils/functions.pyx` are converted unconditionally. `utils/types.pyx` (Singleton) and `handlers/base.pyx` (BaseAppHandler) are converted only if benchmarks show <10% speedup. If `handlers/base.pyx` is converted, `applications/base.pyx` must also be converted due to the `cimport` dependency.

Implements: Spec Module 2 (Cython Cleanup).

---

## Scope

**Unconditional conversions:**
- Convert `navigator/exceptions/exceptions.pyx` → `navigator/exceptions/exceptions.py` (pure Python, same API)
- Delete `navigator/exceptions/exceptions.pxd`
- Delete `navigator/exceptions/exceptions.cpython-*.so` (compiled artifact)
- Delete `navigator/utils/functions.pyx` and `navigator/utils/functions.pxd`
- Move `get_logger` to a pure Python file (e.g., `navigator/utils/functions.py`)
- Confirm `SafeDict` is fully provided by `datamodel` import in `utils/__init__.py`

**Conditional conversions (based on TASK-001 results):**
- If Singleton benchmark <10% speedup: delete `navigator/utils/types.pyx`, rely on `datamodel.typedefs.singleton.Singleton` via `utils/__init__.py`
- If BaseAppHandler benchmark <10% speedup: convert `navigator/handlers/base.pyx` → `navigator/handlers/base.py` AND convert `navigator/applications/base.pyx` → `navigator/applications/base.py` (due to cimport chain)

**Always:**
- Update `setup.py` to remove deleted Cython extension definitions
- Update `navigator/handlers/__init__.py` if base.pyx is converted
- Run existing tests to confirm nothing breaks

**NOT in scope**: Creating new .pyi stubs (TASK-006). SSE View (TASK-005). Dependency changes (TASK-004).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/exceptions/exceptions.py` | CREATE | Pure Python replacement for exceptions.pyx |
| `navigator/exceptions/exceptions.pyx` | DELETE | Replaced by .py version |
| `navigator/exceptions/exceptions.pxd` | DELETE | No longer needed |
| `navigator/utils/functions.py` | CREATE | Pure Python get_logger (replaces .pyx) |
| `navigator/utils/functions.pyx` | DELETE | Replaced by .py version |
| `navigator/utils/functions.pxd` | DELETE | No longer needed |
| `navigator/utils/types.pyx` | CONDITIONAL DELETE | Only if benchmark <10% |
| `navigator/handlers/base.pyx` | CONDITIONAL CONVERT | To .py if benchmark <10% |
| `navigator/handlers/base.pxd` | CONDITIONAL DELETE | If base.pyx converted |
| `navigator/applications/base.pyx` | CONDITIONAL CONVERT | To .py if handlers/base converted |
| `navigator/applications/base.pyi` | CONDITIONAL UPDATE | Update if base.pyx converted |
| `setup.py` | MODIFY | Remove deleted extension definitions |
| `tests/test_exceptions.py` | CREATE | Verify exception API parity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Exception hierarchy (public API to preserve):
from navigator.exceptions import (
    NavException, InvalidArgument, ConfigError, UserNotFound,
    Unauthorized, InvalidAuth, FailedAuth, AuthExpired, ValidationError
)  # verified: navigator/exceptions/__init__.py:5-15

# Also exported: ActionError (in .pyx but NOT in __init__.py)
# NOTE: ActionError is defined at exceptions.pyx:70 but NOT exported in __init__.py
# Check if any code imports it directly before deciding to include

# Utils current state:
from navigator.utils import SafeDict, Singleton  # verified: navigator/utils/__init__.py:1-2
# These import from datamodel, NOT from the Cython .pyx files

# get_logger is imported by:
from ..utils.functions import get_logger  # verified: navigator/handlers/base.pyx:14

# cimport chain (critical):
from ..handlers.base cimport BaseAppHandler  # verified: navigator/applications/base.pyx:17

# Logging (needed for get_logger replacement):
from navconfig.logging import logging, loglevel  # verified: navigator/applications/base.pyx:7
```

### Existing Signatures to Use
```python
# navigator/exceptions/exceptions.pyx — EXACT API to reproduce:
class NavException(Exception):  # line 7
    state: int = 0  # line 10
    def __init__(self, message: str, state: int = 0, **kwargs):  # line 12
        # sets: self.stacktrace, self.message, self.args, self.state
    def __str__(self):  # line 21 → f"{__name__}: {self.message}"
    def get(self):  # line 24 → returns self.message

class InvalidArgument(NavException):  # line 28, state=406
    def __init__(self, message: str = None):  # line 30
class ConfigError(NavException):  # line 33, state=500
class ValidationError(NavException):  # line 39, state=410
class UserNotFound(NavException):  # line 45, state=404
class Unauthorized(NavException):  # line 50, state=401
class InvalidAuth(NavException):  # line 55, state=401
class FailedAuth(NavException):  # line 60, state=403
class AuthExpired(NavException):  # line 65, state=410
class ActionError(NavException):  # line 70, state=400

# navigator/utils/functions.pyx — API to reproduce:
def get_logger(logger_name: str):  # line 7
    # wraps logging.getLogger(logger_name) + logger.setLevel(loglevel)

# navigator/handlers/base.pyx:20 — full class if converting:
# See spec Section 6 for complete signature list

# navigator/applications/base.pyx:20 — full class if converting:
# See spec Section 6 for complete signature list

# setup.py extension list (lines 15-51):
# navigator.utils.types → language="c"
# navigator.utils.functions → language="c"
# navigator.exceptions.exceptions → language="c"
# navigator.types → language="c++"
# navigator.applications.base → language="c++"
# navigator.handlers.base → language="c++"
```

### Does NOT Exist
- ~~`navigator/exceptions/exceptions.py`~~ — does not exist yet (only .pyx exists)
- ~~`navigator/utils/functions.py`~~ — does not exist yet (only .pyx exists)
- ~~`ActionError` in `navigator/exceptions/__init__.py`~~ — defined in .pyx but NOT exported in __init__.py (check if it should be added)
- ~~`navigator.exceptions.exceptions.ActionError` via public import~~ — must import directly from .exceptions.exceptions, not from .exceptions

---

## Implementation Notes

### Pattern to Follow
```python
# Pure Python exception (replace cdef class):
class NavException(Exception):
    """Base class for Navigator exceptions."""

    state: int = 0

    def __init__(self, message: str = '', state: int = 0, **kwargs):
        super().__init__(message)
        self.stacktrace = kwargs.get('stacktrace')
        self.message = message
        self.args = kwargs
        self.state = int(state)

    def __str__(self):
        return f"{__name__}: {self.message}"

    def get(self):
        return self.message
```

### Key Constraints
- **API parity is critical**: Every exception class must have the same `state` code, same `__init__` signature, same `__str__` output
- **`self.args` override**: The Cython code sets `self.args = kwargs` (overriding the Exception default). This must be preserved for backward compat even though it's unusual.
- **`ActionError` export**: Check if `ActionError` should be added to `__init__.py` exports during conversion
- **cimport chain**: If converting `handlers/base.pyx`, MUST also convert `applications/base.pyx` because of `from ..handlers.base cimport BaseAppHandler` at line 17
- **Compiled .so files**: Delete any `.so` artifacts for converted modules to prevent them from shadowing the new `.py` files

### References in Codebase
- `navigator/exceptions/exceptions.pyx` — source to convert
- `navigator/exceptions/__init__.py` — public API (don't change exports unless adding ActionError)
- `navigator/utils/functions.pyx` — source to convert
- `navigator/utils/__init__.py:1-2` — already imports from datamodel (SafeDict, Singleton)
- `navigator/handlers/base.pyx` — conditional conversion source
- `navigator/applications/base.pyx:17` — cimport dependency
- `setup.py:15-51` — extension list to update

---

## Acceptance Criteria

- [ ] `navigator/exceptions/exceptions.py` exists as pure Python with identical API
- [ ] All exception classes instantiate with correct state codes
- [ ] `str(NavException("msg"))` returns same format as Cython version
- [ ] `navigator/utils/functions.py` provides `get_logger()` as pure Python
- [ ] `navigator/utils/functions.pyx` and `.pxd` are deleted
- [ ] `navigator/exceptions/exceptions.pyx` and `.pxd` are deleted
- [ ] `setup.py` no longer lists deleted extensions
- [ ] Conditional: if benchmarks say convert, `handlers/base.py` and `applications/base.py` exist
- [ ] Conditional: if benchmarks say convert, cimport chain is broken cleanly
- [ ] All existing tests pass: `pytest tests/ -v`
- [ ] New exception tests pass: `pytest tests/test_exceptions.py -v`
- [ ] Compiled `.so` artifacts for deleted modules are removed

---

## Test Specification

```python
# tests/test_exceptions.py
import pytest
from navigator.exceptions import (
    NavException, InvalidArgument, ConfigError, ValidationError,
    UserNotFound, Unauthorized, InvalidAuth, FailedAuth, AuthExpired,
)


class TestNavException:
    def test_default_state(self):
        exc = NavException("test")
        assert exc.state == 0
        assert exc.message == "test"

    def test_custom_state(self):
        exc = NavException("test", state=404)
        assert exc.state == 404

    def test_str_format(self):
        exc = NavException("test message")
        assert "test message" in str(exc)

    def test_get_returns_message(self):
        exc = NavException("hello")
        assert exc.get() == "hello"

    def test_stacktrace_kwarg(self):
        exc = NavException("test", stacktrace="trace")
        assert exc.stacktrace == "trace"


class TestExceptionSubclasses:
    @pytest.mark.parametrize("cls,expected_state", [
        (InvalidArgument, 406),
        (ConfigError, 500),
        (ValidationError, 410),
        (UserNotFound, 404),
        (Unauthorized, 401),
        (InvalidAuth, 401),
        (FailedAuth, 403),
        (AuthExpired, 410),
    ])
    def test_default_states(self, cls, expected_state):
        exc = cls()
        assert exc.state == expected_state

    @pytest.mark.parametrize("cls", [
        InvalidArgument, ConfigError, ValidationError,
        UserNotFound, Unauthorized, InvalidAuth, FailedAuth, AuthExpired,
    ])
    def test_custom_message(self, cls):
        exc = cls("custom msg")
        assert exc.message == "custom msg"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Read TASK-001 completion note** for benchmark results — they determine conditional scope
3. **Activate venv**: `source .venv/bin/activate`
4. **Verify the Codebase Contract** — confirm all imports and signatures still match
5. **Convert exceptions first** (unconditional, lowest risk)
6. **Delete utils/functions.pyx** and create pure Python replacement
7. **Check benchmarks** for conditional conversions
8. **Update setup.py** last (after all deletions/conversions)
9. **Delete .so artifacts**: `find navigator/ -name "*.so" | grep -E "(exceptions|functions|types)" | xargs rm -f`
10. **Run tests**: `pytest tests/ -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
