# TASK-027: Package Wiring & pyproject.toml Extra

**Feature**: FEAT-004 — QWorker Background Tasker
**Spec**: `sdd/specs/new-backgroundqueue-tasker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-024
**Assigned-to**: unassigned

---

## Context

Wires the new `taskers` subpackage into the navigator package and adds `qworker`
as an optional extra in `pyproject.toml`.

Implements **Module 4** from the spec (§3).

---

## Scope

- Update `navigator/background/taskers/__init__.py` (created by TASK-024) to
  export `QWorkerTasker` with a lazy import guard:
  ```python
  try:
      from .qworker import QWorkerTasker
  except ImportError:
      QWorkerTasker = None
  ```
- Update `navigator/background/__init__.py` to re-export `QWorkerTasker` from
  the `taskers` subpackage (with the same lazy guard).
- Add a `qworker` optional extra to `pyproject.toml`:
  ```toml
  qworker = [
      "qworker>=2.0.0",
  ]
  ```
- Update the `all` extra to include `qworker`.

**NOT in scope**: Writing the QWorkerTasker class itself (TASK-024). Tests (TASK-028).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/taskers/__init__.py` | MODIFY | Add QWorkerTasker lazy export |
| `navigator/background/__init__.py` | MODIFY | Re-export QWorkerTasker |
| `pyproject.toml` | MODIFY | Add `qworker` optional extra |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator/background/__init__.py — current exports (line 1-5)
from .tracker import JobTracker, RedisJobTracker, JobRecord  # line 2
from .wrappers import TaskWrapper                            # line 3
from .service import BackgroundService                       # line 4
from .queue import BackgroundQueue, BackgroundTask, SERVICE_NAME  # line 5
```

### Existing Signatures to Use

```python
# pyproject.toml — optional-dependencies section starts at line 84
# [project.optional-dependencies]
# Last extra before "all":
# test = [...]    # lines 158-166
# docs = [...]    # lines 169-173
# all = [...]     # lines 176-178
#
# "all" currently: "navigator-api[locale,memcache,uvloop,gunicorn,google,scraping,testing]"
```

### Does NOT Exist

- ~~`navigator.background.taskers`~~ — `__init__.py` exists (created by TASK-024) but has no exports yet
- ~~`navigator.background.QWorkerTasker`~~ — not re-exported from `background/__init__.py` yet

---

## Implementation Notes

### Pattern to Follow

The lazy import pattern is already used in navigator — when an optional dep is
missing, the symbol is set to `None` rather than crashing. Users who need
qworker install the extra; code that doesn't use it is unaffected.

### Key Constraints

- The `pyproject.toml` `qworker` extra should be added BETWEEN the `testing` and
  `dev` sections (around line 128) to maintain alphabetical grouping of
  feature-related extras.
- The `all` extra on line 176-178 must be updated to include `qworker`.

---

## Acceptance Criteria

- [ ] `from navigator.background.taskers import QWorkerTasker` works when qworker is installed
- [ ] `from navigator.background.taskers import QWorkerTasker` returns `None` when qworker is NOT installed
- [ ] `from navigator.background import QWorkerTasker` works (re-export)
- [ ] `pip install navigator-api[qworker]` would pull in `qworker>=2.0.0`
- [ ] `all` extra includes `qworker`
- [ ] `import navigator.background` does NOT crash without qworker installed

---

## Test Specification

```python
import pytest


class TestPackageWiring:
    def test_import_background_without_qworker(self):
        """navigator.background imports cleanly without qworker installed."""
        import navigator.background
        # Should not raise

    def test_qworkertasker_export(self):
        """QWorkerTasker is accessible from navigator.background."""
        from navigator.background import QWorkerTasker
        # QWorkerTasker is either the class or None (if qw not installed)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/new-backgroundqueue-tasker.spec.md`
2. **Check dependencies** — TASK-024 must be completed (creates the package)
3. **Verify the Codebase Contract** — re-read `background/__init__.py` and `pyproject.toml`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the package wiring
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
