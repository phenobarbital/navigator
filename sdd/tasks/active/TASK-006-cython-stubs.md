# TASK-006: Cython Interface Stubs — .pxd and .pyi for Remaining Modules

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-002
**Assigned-to**: unassigned

---

## Context

After TASK-002 removes Cython from modules with no performance benefit, the remaining Cython modules need proper `.pxd` (Cython declaration) and `.pyi` (Python type stub) files for IDE support and downstream `cimport`. Currently `types.pyx` has neither, `handlers/base.pyx` has a minimal `.pxd` but no `.pyi`, and `applications/base.pyx` has a `.pyi` but may need updating.

Implements: Spec Module 6 (Cython Interface Stubs).

---

## Scope

**Depends on TASK-002 outcomes — which modules survive:**

At minimum (these stay Cython regardless of benchmarks):
- `navigator/types.pyx` — create `navigator/types.pxd` and `navigator/types.pyi`
- `navigator/applications/base.pyx` — verify and update existing `navigator/applications/base.pyi`

Conditional (only if benchmarks kept them as Cython):
- `navigator/handlers/base.pyx` — create `navigator/handlers/base.pyi`, update existing `navigator/handlers/base.pxd`
- `navigator/utils/types.pyx` — create `.pxd` and `.pyi` if Singleton stayed Cython

**NOT in scope**: Converting any Cython files (TASK-002). Writing tests. Modifying existing `.pyx` source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/types.pxd` | CREATE | Cython declaration for types.pyx |
| `navigator/types.pyi` | CREATE | Python type stub for types.pyx |
| `navigator/applications/base.pyi` | MODIFY | Verify and update accuracy |
| `navigator/handlers/base.pyi` | CONDITIONAL CREATE | If handlers/base stays Cython |
| `navigator/handlers/base.pxd` | CONDITIONAL MODIFY | Update if handlers/base stays Cython |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Types module (always stays Cython):
from navigator.types import WebApp, URL, HTTPMethod, HTTPRequest, HTTPResponse, HTTPHandler, HTTPRoute
# verified: navigator/types.pyx:12-23,26
```

### Existing Signatures to Use
```python
# navigator/types.pyx — full signature for .pxd/.pyi:
# Type aliases (lines 12-23):
WebApp = web.Application  # line 12
HTTPMethod = str  # line 13
HTTPLocation = str  # line 14
HTTPRequest = web.Request  # line 15
HTTPResponse = web.StreamResponse  # line 16
HTTPHandler = Callable[[HTTPRequest], Awaitable[HTTPResponse]]  # line 17
HTTPRoute = Tuple[HTTPMethod, HTTPLocation, HTTPHandler]  # lines 19-23

# URL class (lines 26-124):
cdef class URL:
    cdef str value  # line 27
    cdef str scheme  # line 28
    cdef str path  # line 29
    cdef str host  # line 30
    cdef str port  # line 31
    cdef str netloc  # line 32
    cdef str query  # line 33
    cdef str fragment  # line 34
    cdef dict params  # line 35
    cdef bool is_absolute  # line 36
    def __init__(self, str value)  # line 41
    cpdef URL change_scheme(self, str scheme)  # line 96
    cpdef URL change_host(self, str host)  # line 109
    # Properties: host, port, qs_params, scheme, netloc

# navigator/applications/base.pyi (existing, line-by-line):
# Already has: get_app, setup_app, event_loop, __setitem__, __getitem__,
#              __repr__, active_extensions, setup
# MISSING from existing .pyi:
#   - __init__ signature with all parameters
#   - handler, description, host, port, path, title, contact, use_ssl, debug, logger attributes

# navigator/handlers/base.pxd (existing):
cdef class BaseAppHandler:  # line 4
    pass  # line 5 — MINIMAL, needs full attribute and method declarations

# navigator/handlers/base.pyx (if staying Cython):
# Full signature in spec Section 6 — 20+ methods and attributes
```

### Does NOT Exist
- ~~`navigator/types.pxd`~~ — does not exist, must be created
- ~~`navigator/types.pyi`~~ — does not exist, must be created
- ~~`navigator/handlers/base.pyi`~~ — does not exist
- ~~`navigator/utils/types.pxd`~~ — does not exist (only if Singleton stays Cython)

---

## Implementation Notes

### Pattern to Follow — .pxd file
```cython
# navigator/types.pxd
from libcpp cimport bool

cdef class URL:
    cdef str value
    cdef str scheme
    cdef str path
    cdef str host
    cdef str port
    cdef str netloc
    cdef str query
    cdef str fragment
    cdef dict params
    cdef bool is_absolute

    cpdef URL change_scheme(self, str scheme)
    cpdef URL change_host(self, str host)
```

### Pattern to Follow — .pyi file
```python
# navigator/types.pyi
from typing import Tuple, Callable, Awaitable, Optional, Dict
from aiohttp import web

WebApp = web.Application
HTTPMethod = str
HTTPLocation = str
HTTPRequest = web.Request
HTTPResponse = web.StreamResponse
HTTPHandler = Callable[[HTTPRequest], Awaitable[HTTPResponse]]
HTTPRoute = Tuple[HTTPMethod, HTTPLocation, HTTPHandler]

class URL:
    value: str
    scheme: str
    path: str
    host: str
    port: str
    netloc: str
    query: str
    fragment: str
    params: Dict[str, list]
    is_absolute: bool

    def __init__(self, value: str) -> None: ...
    def change_scheme(self, scheme: str) -> 'URL': ...
    def change_host(self, host: str) -> 'URL': ...
    @property
    def qs_params(self) -> Dict[str, list]: ...
```

### Key Constraints
- `.pxd` files declare C-level interfaces for `cimport` — must match the `.pyx` exactly
- `.pyi` files provide Python type stubs for IDE support — use standard Python typing
- The existing `applications/base.pyi` is incomplete (missing `__init__` params) — update it
- The existing `handlers/base.pxd` is minimal (`pass` body) — expand with full declarations if kept

### References in Codebase
- `navigator/types.pyx:26-124` — URL class to stub
- `navigator/applications/base.pyi` — existing stub to update
- `navigator/handlers/base.pxd` — existing minimal declaration
- `navigator/applications/base.pyx:17` — cimport of BaseAppHandler (requires .pxd)

---

## Acceptance Criteria

- [ ] `navigator/types.pxd` exists with full URL cdef declarations
- [ ] `navigator/types.pyi` exists with full URL type stubs and type aliases
- [ ] `navigator/applications/base.pyi` is updated with `__init__` params and all attributes
- [ ] Conditional: `navigator/handlers/base.pyi` exists if handlers/base stays Cython
- [ ] All `.pxd` files match their `.pyx` counterparts exactly
- [ ] All `.pyi` files are valid Python (parseable by mypy)
- [ ] IDE auto-completion works for stubbed classes (manual verification)

---

## Test Specification

```python
# No runtime tests — stubs are checked by mypy:
# mypy navigator/types.pyi
# mypy navigator/applications/base.pyi
# mypy navigator/handlers/base.pyi  (if created)
```

---

## Agent Instructions

When you pick up this task:

1. **Check TASK-002 completion note** to know which modules stayed Cython
2. **Read** each surviving `.pyx` file for exact signatures
3. **Create** `.pxd` files matching C-level declarations
4. **Create** `.pyi` files with Python typing
5. **Update** existing `applications/base.pyi` for completeness
6. **Verify** with `mypy` if available

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
