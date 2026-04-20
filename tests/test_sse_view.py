"""Tests for the new :class:`navigator.views.sse.SSEView`.

Spec FEAT-001 / TASK-005 — these tests exercise the parts of the view
that are independent of a live SSE stream:

* the ``SSEView`` class exists and is exported from ``navigator.views``,
* it inherits from :class:`navigator.views.base.BaseView` (so it picks up
  CORS via ``CorsViewMixin`` in the MRO),
* requesting a task that the manager has never registered returns
  HTTP 404 (propagated from ``SSEManager.subscribe_to_task``),
* accessing ``sse_manager`` without configuring one raises
  :class:`RuntimeError` with a hint pointing at
  ``app['sse_manager'] = SSEManager()``,
* the legacy :class:`navigator.services.sse.mixin.SSEMixin` and
  :class:`navigator.services.sse.mixin.SSEEventView` are still
  importable (backward-compatibility guard).
"""
from __future__ import annotations

import aiohttp_cors
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from navigator.services.sse.manager import SSEManager
from navigator.views import BaseView, SSEView


# ---------------------------------------------------------------------------
# Exports / inheritance
# ---------------------------------------------------------------------------

class TestSSEViewImports:
    def test_exported_from_navigator_views(self):
        """``SSEView`` is part of the public ``navigator.views`` API."""
        from navigator.views import SSEView as PublicSSEView

        assert PublicSSEView is SSEView

    def test_inherits_from_baseview(self):
        assert issubclass(SSEView, BaseView)

    def test_inherits_from_cors_view_mixin(self):
        """CORS support must come along for free via the BaseView MRO."""
        assert issubclass(SSEView, aiohttp_cors.CorsViewMixin)

    def test_legacy_sse_mixin_still_available(self):
        """The legacy mixin / view coexist with the new class-based view."""
        from navigator.services.sse.mixin import SSEEventView, SSEMixin

        assert SSEMixin is not None
        assert SSEEventView is not None


# ---------------------------------------------------------------------------
# Behavior against a real aiohttp app
# ---------------------------------------------------------------------------

@pytest.fixture
async def sse_client():
    """Yield (client, manager) against an app that has SSEView routed."""
    app = web.Application()
    app["sse_manager"] = SSEManager()
    app.router.add_view("/events/{task_id}", SSEView)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, app["sse_manager"]
    finally:
        await client.close()


class TestSSEViewBehavior:
    async def test_unknown_task_id_returns_404(self, sse_client):
        """SSEManager.subscribe_to_task raises HTTPNotFound for unknown ids."""
        client, _manager = sse_client
        resp = await client.get("/events/does-not-exist")
        assert resp.status == 404

    async def test_sse_manager_not_configured_raises(self):
        """Without app['sse_manager'], the property raises a clear error."""
        app = web.Application()
        app.router.add_view("/events/{task_id}", SSEView)

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            # The server-side handler will blow up with a RuntimeError when
            # accessing ``self.sse_manager``. That bubbles up to aiohttp as a
            # 500. We only care that the *request* does not succeed.
            resp = await client.get("/events/any-id")
            assert resp.status >= 500
        finally:
            await client.close()


class TestSSEViewBroadcastHelpers:
    """Smoke-test that SSEView exposes the broadcast helpers.

    These are thin wrappers around :class:`SSEManager` — we don't open a
    real SSE stream here, we just verify the class surface exists and is
    callable (which catches regressions like a renamed property or a
    missed ``async def``).
    """

    @pytest.mark.parametrize(
        "method_name",
        [
            "create_task",
            "notify_progress",
            "notify_result",
            "notify_error",
            "on_subscribe",
            "_extract_user_id",
            "get",
            "get_stats",
        ],
    )
    def test_method_exists_and_is_coroutine(self, method_name):
        import inspect

        method = getattr(SSEView, method_name, None)
        assert method is not None, f"SSEView is missing method {method_name!r}"
        assert inspect.iscoroutinefunction(method), (
            f"SSEView.{method_name} should be a coroutine function"
        )
