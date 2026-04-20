# TASK-005: SSE View — Class-Based View for Server-Sent Events

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: sdd-worker

---

## Context

Navigator has an `SSEManager` and `SSEMixin` but no proper class-based View that inherits from `BaseView`. The existing `SSEEventView` in `services/sse/mixin.py` inherits from `SSEMixin` only — it lacks CORS support, JSON encoding, session integration, and the standard BaseView lifecycle. This task creates a proper `SSEView` in the views package.

Implements: Spec Module 5 (SSE View).

---

## Scope

- Create `navigator/views/sse.py` with `SSEView` class inheriting from `BaseView`
- `SSEView` wraps `SSEManager` with proper view lifecycle (CORS, session, JSON)
- Provides a developer-friendly API: override hooks for custom SSE behavior
- Export `SSEView` from `navigator/views/__init__.py`
- Existing `SSEMixin` and `SSEEventView` in `services/sse/mixin.py` are preserved (backward compat)
- Add tests for SSEView

**NOT in scope**: Modifying SSEManager. Changing SSEMixin or SSEEventView. Dependency changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/views/sse.py` | CREATE | SSEView class |
| `navigator/views/__init__.py` | MODIFY | Export SSEView |
| `tests/test_sse_view.py` | CREATE | SSEView tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Base class for SSEView:
from navigator.views import BaseView  # verified: navigator/views/__init__.py:7
# BaseView inherits from: aiohttp_cors.CorsViewMixin, BaseHandler, web.View
# verified: navigator/views/base.py:596

# SSE support:
from navigator.services.sse.manager import SSEManager, SSEConnection
# verified: navigator/services/sse/manager.py:36,18
from aiohttp_sse import sse_response, EventSourceResponse
# verified: navigator/responses.py:14

# aiohttp:
from aiohttp import web  # verified: navigator/views/base.py:10

# JSON encoding:
from datamodel.parsers.json import json_encoder  # verified: navigator/views/base.py:19

# Session:
from navigator_session import get_session  # verified: navigator/views/base.py:26

# Logging:
from navconfig.logging import logging  # verified: navigator/views/base.py:25
```

### Existing Signatures to Use
```python
# navigator/views/base.py:596
class BaseView(aiohttp_cors.CorsViewMixin, BaseHandler, web.View):
    cors_config = {"*": ResourceOptions(...)}  # lines 598-606
    def __init__(self, request, *args, **kwargs)  # line 608
    # Inherited from BaseHandler:
    def json_response(self, response=None, ...) -> JSONResponse  # line 121
    def response(self, response="", status=200, ...) -> web.Response  # line 101
    async def session(self)  # line 66

# navigator/services/sse/manager.py:36
class SSEManager:
    async def subscribe_to_task(self, request, task_id, user_id=None) -> web.StreamResponse  # line 110
    async def create_task_notification(self, task_type, user_id=None, metadata=None) -> str  # line 81
    async def broadcast_task_progress(self, task_id, progress_data) -> int  # line 175
    async def broadcast_task_result(self, task_id, result_data, close_connections=True) -> int  # line 203
    async def broadcast_task_error(self, task_id, error_data, close_connections=True) -> int  # line 244
    def get_stats(self) -> Dict[str, Any]  # line 377

# navigator/services/sse/mixin.py:12 — SSEMixin pattern to follow:
class SSEMixin:
    @property
    def sse_manager(self) -> SSEManager  # line 49 — gets from request.app['sse_manager']
    async def create_task(self, task_type, ...) -> str  # line 59
    async def notify_progress(self, task_id, progress_data) -> int  # line 86
    async def notify_result(self, task_id, result_data, ...) -> int  # line 103
    async def notify_error(self, task_id, error_data, ...) -> int  # line 124
    async def _extract_user_id(self) -> Optional[str]  # line 145

# navigator/services/sse/mixin.py:175 — existing SSEEventView (to coexist with):
class SSEEventView(SSEMixin):
    async def get(self) -> web.StreamResponse  # line 184
```

### Does NOT Exist
- ~~`navigator/views/sse.py`~~ — does not exist yet, to be created
- ~~`navigator.views.SSEView`~~ — does not exist yet
- ~~`BaseView.sse_manager`~~ — BaseView does not have SSE support; SSEView adds it
- ~~`aiohttp` built-in SSE support~~ — aiohttp has no native SSE; uses aiohttp-sse

---

## Implementation Notes

### Pattern to Follow
```python
# navigator/views/sse.py
from typing import Optional, Dict, Any
from aiohttp import web
from aiohttp_sse import sse_response
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging
from .base import BaseView
from ..services.sse.manager import SSEManager


class SSEView(BaseView):
    """Class-based View for Server-Sent Events.

    Inherits CORS, session, JSON encoding from BaseView.
    Wraps SSEManager for connection lifecycle.

    Usage:
        class MySSE(SSEView):
            async def on_subscribe(self, request, task_id):
                # Custom logic before subscription
                pass

        app.router.add_view('/events/{task_id}', MySSE)
    """

    async def get(self) -> web.StreamResponse:
        task_id = self.request.match_info.get('task_id')
        if not task_id:
            return self.error(reason="task_id is required", status=400)
        # delegate to SSEManager
        ...

    @property
    def sse_manager(self) -> SSEManager:
        if 'sse_manager' not in self.request.app:
            raise RuntimeError(
                "SSE Manager not configured. "
                "Add SSEManager to your app: app['sse_manager'] = SSEManager()"
            )
        return self.request.app['sse_manager']
```

### Key Constraints
- `BaseView.__init__` takes `request` as first argument (line 608) — SSEView must respect this
- `BaseView` is an `aiohttp.web.View` subclass — `self.request` is available automatically
- CORS is handled by `aiohttp_cors.CorsViewMixin` in the MRO — SSEView inherits it
- SSEView must NOT break existing `SSEMixin` or `SSEEventView` — it coexists
- The `sse_manager` property pattern comes from `SSEMixin.sse_manager` (line 49-57)

### References in Codebase
- `navigator/views/base.py:596-645` — BaseView class to inherit from
- `navigator/services/sse/mixin.py:12-173` — SSEMixin pattern to follow
- `navigator/services/sse/mixin.py:175-195` — SSEEventView to coexist with
- `navigator/services/sse/manager.py:110-173` — subscribe_to_task method to delegate to
- `navigator/views/__init__.py:18-28` — __all__ export list to update

---

## Acceptance Criteria

- [ ] `navigator/views/sse.py` exists with `SSEView(BaseView)` class
- [ ] `SSEView` has `sse_manager` property accessing `request.app['sse_manager']`
- [ ] `SSEView.get()` handles SSE subscription via SSEManager
- [ ] CORS works on SSEView (inherited from BaseView/CorsViewMixin)
- [ ] `SSEView` is exported from `navigator/views/__init__.py`
- [ ] Existing `SSEMixin` and `SSEEventView` still importable and unchanged
- [ ] Tests pass: `pytest tests/test_sse_view.py -v`
- [ ] Import works: `from navigator.views import SSEView`

---

## Test Specification

```python
# tests/test_sse_view.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from navigator.views.sse import SSEView
from navigator.services.sse.manager import SSEManager


@pytest.fixture
async def sse_app(aiohttp_client):
    app = web.Application()
    app['sse_manager'] = SSEManager()
    app.router.add_view('/events/{task_id}', SSEView)
    client = await aiohttp_client(app)
    return client, app['sse_manager']


class TestSSEView:
    async def test_import(self):
        from navigator.views import SSEView
        assert SSEView is not None

    async def test_missing_task_id(self, sse_app):
        client, _ = sse_app
        # SSEView requires task_id in URL
        # Test behavior with invalid task_id
        resp = await client.get('/events/nonexistent-task')
        assert resp.status in (404, 400)

    async def test_sse_manager_not_configured(self):
        app = web.Application()
        # No sse_manager set
        app.router.add_view('/events/{task_id}', SSEView)
        # Should raise RuntimeError when accessing sse_manager
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Read** `navigator/views/base.py:596-645` — understand BaseView
3. **Read** `navigator/services/sse/mixin.py` — understand SSEMixin pattern
4. **Read** `navigator/services/sse/manager.py:110-173` — understand subscribe_to_task
5. **Create** `navigator/views/sse.py` with SSEView
6. **Update** `navigator/views/__init__.py` to export SSEView
7. **Write tests** in `tests/test_sse_view.py`
8. **Run tests**: `pytest tests/test_sse_view.py -v`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-20
**Commit**: `feat-001-aiohttp-navigator-modernization` / e6dd2aa

**What shipped**:

- `navigator/views/sse.py` — new module with `class SSEView(BaseView)`:
  - `sse_manager` property reads `request.app['sse_manager']`
    (RuntimeError with a clear hint if missing).
  - `async get()` resolves `task_id` from `match_info`, invokes an
    overridable `on_subscribe` hook, extracts `user_id`, then
    delegates to `SSEManager.subscribe_to_task`.
  - `async get_stats()` returns a JSON snapshot of `SSEManager.get_stats`.
  - Broadcast helpers `create_task` / `notify_progress` /
    `notify_result` / `notify_error` (same signatures as
    `SSEMixin`).
  - `_extract_user_id` default: Navigator session → `?user_id=`
    query parameter → None. Overridable.

- `navigator/views/__init__.py` — exports `SSEView` and adds it to
  `__all__`.

- `tests/test_sse_view.py` — 14 tests covering:
  - Export surface (`from navigator.views import SSEView`).
  - Inheritance chain (`BaseView`, `aiohttp_cors.CorsViewMixin`).
  - Backward compat (legacy `SSEMixin` and `SSEEventView` still import).
  - HTTP 404 propagated from SSEManager for unknown task ids.
  - 5xx response when no `sse_manager` is registered on the app.
  - Method-surface guard: every expected async method exists and is a
    coroutine function.

**Backward compatibility**: `navigator/services/sse/mixin.py` was not
touched. Spec §8 answers "coexist" for the old vs new path, and that is
what is delivered. Consumers of `SSEMixin` / `SSEEventView` continue to
work unchanged.

**Verification**:
- `python -c "from navigator.views import SSEView"` succeeds.
- `pytest tests/test_sse_view.py -v` → **14 passed**.
- `pytest tests/` → **46 passed, 0 failed**.
- `issubclass(SSEView, BaseView)` → `True`.

**Deviations from spec**: none.
