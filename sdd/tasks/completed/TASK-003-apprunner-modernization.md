# TASK-003: AppRunner Modernization — Fix Bug and Remove Legacy Runner

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: sdd-worker

---

## Context

`navigator/navigator.py` has a bug in `_run_unix()` where parameter `unix_path` is referenced as `path` (lines 673, 680), and a dead `_run_legacy()` method that nobody calls. This task fixes the bug and removes the dead code.

Implements: Spec Module 3 (AppRunner Modernization).

---

## Scope

- Fix `_run_unix()` bug: replace `path` with `unix_path` at lines 673 and 680
- Remove `_run_legacy()` method entirely (lines 839-902)
- Remove `use_legacy_runner` flag handling in `run()` (lines 800-801)
- Verify `start_server()` → `_run_tcp()`/`_run_unix()` path still works

**NOT in scope**: SSL tests (TASK-007). Dependency changes (TASK-004). Any changes outside `navigator/navigator.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/navigator.py` | MODIFY | Fix _run_unix bug, remove _run_legacy |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator/navigator.py relevant imports:
from aiohttp import web  # verified: navigator/navigator.py:7
from pathlib import Path  # verified: navigator/navigator.py:4
import ssl  # verified: navigator/navigator.py:2
```

### Existing Signatures to Use
```python
# navigator/navigator.py:638
async def _run_unix(
    self,
    app: web.Application,
    unix_path: Union[str, Path],  # parameter is "unix_path"
    **kwargs
) -> None:
    # BUG at line 673: path=str(path)  — should be path=str(unix_path)
    # BUG at line 680: f"...{path}"    — should be f"...{unix_path}"

# navigator/navigator.py:759
def run(self, host=None, port=None, ssl_context=None, unix_path=None, **kwargs):
    # Line 800-801: use_legacy_runner check to REMOVE
    # if kwargs.get('use_legacy_runner', False):
    #     self._run_legacy(**kwargs)
    #     return

# navigator/navigator.py:839-902
def _run_legacy(self, **kwargs) -> None:
    # ENTIRE METHOD TO REMOVE
```

### Does NOT Exist
- ~~Any callers of `_run_legacy()`~~ — grep confirms no callers exist outside the method definition and the `use_legacy_runner` check in `run()`
- ~~`navigator.navigator.Navigator._run_legacy` after this task~~ — will be removed

---

## Implementation Notes

### Key Constraints
- The `_run_unix` fix is a simple variable rename: `path` → `unix_path` at exactly 2 locations
- When removing `_run_legacy`, also remove the `use_legacy_runner` kwarg check (line 800-801) in `run()`
- There's also a utility function `create_unix_site` at line 969 that has the same bug (`path=str(path)`) — check if the parameter there is also wrong
- Do NOT modify `_run_tcp()`, `start_server()`, or any other methods

### References in Codebase
- `navigator/navigator.py:638-684` — `_run_unix()` with bug
- `navigator/navigator.py:759-837` — `run()` with legacy runner check
- `navigator/navigator.py:839-902` — `_run_legacy()` to delete
- `navigator/navigator.py:955-971` — `create_unix_site()` utility, check for same bug

---

## Acceptance Criteria

- [ ] `_run_unix()` uses `unix_path` parameter consistently (not `path`)
- [ ] `_run_legacy()` method no longer exists
- [ ] `use_legacy_runner` flag handling removed from `run()`
- [ ] `create_unix_site()` utility also fixed if it has the same bug
- [ ] No other methods modified
- [ ] Existing tests pass: `pytest tests/ -v`

---

## Test Specification

```python
# Minimal verification — the bug fix is straightforward
# Verify by reading the code after modification:
# grep -n "path=str(path)" navigator/navigator.py  → should return 0 matches
# grep -n "_run_legacy" navigator/navigator.py  → should return 0 matches
# grep -n "use_legacy_runner" navigator/navigator.py  → should return 0 matches
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `navigator/navigator.py` lines 638-902 for full context
2. **Fix the bug** at lines 673 and 680
3. **Check** `create_unix_site()` at ~line 969 for the same issue
4. **Remove** `_run_legacy()` and `use_legacy_runner` handling
5. **Verify** with grep that no references remain
6. **Run tests**: `pytest tests/ -v`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-20
**Commit**: `feat-001-aiohttp-navigator-modernization` / 23d49e8

**Bug fix (`_run_unix`)**: the two references to the undefined name `path`
(line 673 inside the `web.UnixSite(...)` call and line 680 in the
"Navigator started on unix socket..." log message) were replaced with
the actual parameter `unix_path`. The method docstring was also updated
from `path: Unix socket path` to `unix_path: Unix socket path` so the
parameter documentation matches the signature.

**Legacy runner removal**:
- The `_run_legacy()` method was deleted in full (64 lines).
- The `use_legacy_runner` kwarg branch inside `run()` that dispatched
  to `_run_legacy()` was removed.
- `run()`'s docstring was updated — it no longer advertises "legacy
  compatibility".

**Scope guard**: the task flagged `create_unix_site()` (utility function
at the bottom of the module) as a potential same-bug site. Verified in
place — its parameter is already named `path` and the body correctly
uses `path=str(path)`; no change needed, no change made.

**Verification**:

| Check | Result |
|---|---|
| `grep _run_legacy navigator/navigator.py` | 0 matches |
| `grep use_legacy_runner navigator/navigator.py` | 0 matches |
| `grep 'path=str(path)' navigator/navigator.py` | only in `create_unix_site` (intentional) |
| `Application._run_legacy` attribute check | `False` (removed) |
| `Application._run_unix`, `Application.run` attribute checks | `True` (preserved) |
| `pytest tests/` | 32 passed |

**Deviations from spec**: none.
