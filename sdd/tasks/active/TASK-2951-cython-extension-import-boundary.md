# TASK-2951: Remove Cython extension runtime import coupling

**Feature**: FEAT-007 — Navigator Wheel Build Infrastructure Refactor
**Spec**: `sdd/specs/wheel-build-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2950
**Assigned-to**: unassigned

---

## Context

Implement Module 2. The release failure was not Cython compilation: the
post-build import of `navigator.types` executed an unused `navconfig` import,
which bootstrapped configuration in cibuildwheel's empty temporary directory.
The Cython extension declarations themselves must remain unchanged in behavior.

## Scope

- Remove the unused `from navconfig import config, DEBUG` line from
  `navigator/types.pyx`.
- Preserve the `navigator.utils.types` C extension and `navigator.types` C++
  extension declarations in `setup.py`.
- Confirm the Cython source still compiles and the module's public URL behavior
  is unchanged.
- Add or update a focused import regression test if needed.

**NOT in scope**: packaging metadata changes beyond TASK-2950, release workflow
changes, runtime navconfig imports elsewhere, or Rust/maturin integration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/types.pyx` | MODIFY | Remove dead navconfig import. |
| `setup.py` | VERIFY only | Preserve extension inventory and cythonize directives. |
| `tests/` focused Cython/import test path | CREATE or MODIFY | Regression coverage for isolated module import. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator/types.pyx:4-8
from typing import Tuple, Callable, Awaitable
from urllib.parse import urlparse, parse_qs, ParseResult
from aiohttp import web
from navconfig import config, DEBUG
from .exceptions.exceptions import ValidationError
```

The navconfig import is the specifically verified dead import to remove.

### Existing Signatures to Use

```python
# setup.py:29-42
Extension(name="navigator.utils.types", sources=["navigator/utils/types.pyx"], language="c")
Extension(name="navigator.types", sources=["navigator/types.pyx"], language="c++")

# setup.py:46-56
setup(ext_modules=cythonize(extensions, compiler_directives={...}))
```

### Does NOT Exist

- ~~A Rust extension declaration~~ — no Cargo, PyO3, maturin, or Rust module.
- ~~A need for navconfig configuration during Cython compilation~~ — setup.py
  imports only setuptools and Cython.
- ~~A permission to remove runtime navconfig imports from other modules~~ —
  `navigator/conf.py` and other runtime modules legitimately use navconfig.

## Implementation Notes

### Pattern to Follow

Keep `setup.py` as a Cython-only boundary, matching
`/home/jesuslara/proyectos/navconfig/setup.py:8-73`. Do not refactor unrelated
URL parsing or Cython directives.

### Key Constraints

- The extension names and C/C++ language modes are part of the wheel contract.
- The change must not alter `URL` behavior or public imports.
- Verify the generated extension can be imported without a configured navconfig
  project when the module itself does not need configuration.

### References in Codebase

- `navigator/types.pyx:1-56`
- `navigator/types.pxd`
- `setup.py:9-56`
- `navigator/__init__.py:30-50`

## Acceptance Criteria

- [ ] `navigator/types.pyx` no longer imports unused navconfig configuration names.
- [ ] Both Cython extension declarations remain present and correctly typed.
- [ ] Focused Cython/import regression coverage passes.
- [ ] No unrelated runtime navconfig imports are changed.
- [ ] No Rust or maturin tooling is introduced.

## Test Specification

```python
def test_navigator_types_import_does_not_bootstrap_navconfig():
    ...

def test_url_extension_contract_is_unchanged():
    ...
```

## Agent Instructions

Verify TASK-2950 is complete before implementation. Re-read the Cython source
and setup declarations, then run the narrowest available Cython/import tests.

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: 

**Deviations from spec**: none | describe if any
