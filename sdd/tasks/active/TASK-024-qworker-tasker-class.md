# TASK-024: QWorkerTasker Class

**Feature**: FEAT-004 — QWorker Background Tasker
**Spec**: `sdd/specs/new-backgroundqueue-tasker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-004. It creates the `QWorkerTasker` class
that wraps `qw.client.QClient` and provides a `dispatch()` method supporting
three remote execution modes: `run`, `queue`, and `publish`.

Implements **Module 1** from the spec (§3).

---

## Scope

- Create `navigator/background/taskers/` package (empty `__init__.py`).
- Create `navigator/background/taskers/qworker.py` with `QWorkerTasker` class.
- `QWorkerTasker.__init__()` must lazy-import `qw.client.QClient`. If `qw` is
  not installed, raise `ImportError` with message:
  `"qworker is required for remote task dispatch. Install it with: pip install navigator-api[qworker]"`
- `QWorkerTasker.dispatch(fn, *args, remote_mode="run", tracker=None, task_uuid=None, **kwargs)`:
  - `"run"` → call `await self._client.run(fn, *args, use_wrapper=False, **kwargs)`,
    update tracker to `done` with result.
  - `"queue"` → call `await self._client.queue(fn, *args, use_wrapper=True, **kwargs)`,
    update tracker status to `"queued_remote"`.
  - `"publish"` → call `await self._client.publish(fn, *args, use_wrapper=True, **kwargs)`,
    update tracker status to `"queued_remote"`.
  - On exception: update tracker to `failed`, re-raise.
- `QWorkerTasker.close()` — no-op for now (QClient creates per-call connections).
- Use `self.logger = logging.getLogger('NAV.Queue.QWorkerTasker')`.

**NOT in scope**: Modifying TaskWrapper or BackgroundService (TASK-025, TASK-026).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/background/taskers/__init__.py` | CREATE | Package init, empty for now |
| `navigator/background/taskers/qworker.py` | CREATE | QWorkerTasker implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Tracker — for updating job status after dispatch
from navigator.background.tracker import JobTracker  # navigator/background/__init__.py:2

# Logging
from navconfig.logging import logging  # used throughout navigator codebase

# QClient — LAZY IMPORT ONLY inside __init__()
# from qw.client import QClient  # qw/client.py:58 — do NOT import at module level
```

### Existing Signatures to Use

```python
# qw/client.py:58
class QClient:
    def __init__(self, worker_list: list = None, timeout: int = 5): ...  # line 72

    async def run(self, fn: Any, *args, use_wrapper: bool = False, **kwargs): ...  # line 326
    # Returns: actual result (deserialized). Raises on error.

    async def queue(self, fn: Any, *args, use_wrapper: bool = True, **kwargs): ...  # line 420
    # Returns: {"status": "Queued", "task": repr, "message": confirmation}

    async def publish(self, fn: Any, *args, use_wrapper: bool = True, **kwargs): ...  # line 484
    # Returns: {"status": "Queued", "task": repr, "message": stream_id}

# navigator/background/tracker/memory.py:12
class JobTracker:
    async def set_running(self, job_id: str) -> None: ...   # line 83
    async def set_done(self, job_id: str, result: Any = None) -> None: ...  # line 89
    async def set_failed(self, job_id: str, exc: Exception) -> None: ...    # line 96
```

### Does NOT Exist

- ~~`QClient.connect()`~~ — no explicit connect method; connections are per-call
- ~~`QClient.close()`~~ — no global close; each call manages its own writer
- ~~`QClient.status(task_id)`~~ — no per-task status tracking in qworker
- ~~`QClient.result(task_id)`~~ — no result store; results returned inline from `run()`
- ~~`navigator.background.taskers`~~ — package does not exist yet (this task creates it)

---

## Implementation Notes

### Pattern to Follow

```python
class QWorkerTasker:
    _VALID_MODES = ("run", "queue", "publish")

    def __init__(
        self,
        worker_list: list[tuple[str, int]] | None = None,
        timeout: int = 5,
        default_mode: str = "run",
    ) -> None:
        try:
            from qw.client import QClient
        except ImportError as exc:
            raise ImportError(
                "qworker is required for remote task dispatch. "
                "Install it with: pip install navigator-api[qworker]"
            ) from exc
        if default_mode not in self._VALID_MODES:
            raise ValueError(...)
        self._client = QClient(worker_list=worker_list, timeout=timeout)
        self.default_mode = default_mode
        self.logger = logging.getLogger('NAV.Queue.QWorkerTasker')

    async def dispatch(self, fn, *args, remote_mode=None, tracker=None, task_uuid=None, **kwargs):
        mode = remote_mode or self.default_mode
        # dispatch based on mode ...
```

### Key Constraints

- `qw.client` MUST be lazy-imported inside `__init__()`, never at module level.
- All three modes are async — no blocking I/O.
- Tracker updates are best-effort (wrapped in try/except so dispatch doesn't fail if tracker fails).

---

## Acceptance Criteria

- [ ] `navigator/background/taskers/__init__.py` exists
- [ ] `navigator/background/taskers/qworker.py` contains `QWorkerTasker` class
- [ ] `QWorkerTasker()` raises `ImportError` when `qw` is not installed
- [ ] `dispatch()` with `remote_mode="run"` calls `QClient.run()` and returns result
- [ ] `dispatch()` with `remote_mode="queue"` calls `QClient.queue()`
- [ ] `dispatch()` with `remote_mode="publish"` calls `QClient.publish()`
- [ ] Invalid `remote_mode` raises `ValueError`
- [ ] Tracker is updated on success and failure

---

## Test Specification

```python
# tests/test_qworker_tasker.py (partial — full tests in TASK-028)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestQWorkerTaskerInit:
    def test_init_with_qworker(self):
        """QWorkerTasker initializes when qw is installed."""
        from navigator.background.taskers.qworker import QWorkerTasker
        tasker = QWorkerTasker()
        assert tasker.default_mode == "run"

    def test_init_missing_qworker(self, monkeypatch):
        """Raises ImportError with helpful message when qw missing."""
        # ... mock import to fail ...

    def test_init_invalid_mode(self):
        """Raises ValueError for invalid default_mode."""
        # ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/new-backgroundqueue-tasker.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `qw.client.QClient` signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the `QWorkerTasker` class
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-024-qworker-tasker-class.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
