"""Server-Sent Events (SSE) class-based view.

Spec FEAT-001 / TASK-005 — wires :class:`~navigator.services.sse.manager.SSEManager`
into the standard Navigator view lifecycle. Unlike the legacy
:class:`navigator.services.sse.mixin.SSEEventView`, :class:`SSEView` inherits
from :class:`~navigator.views.base.BaseView`, which means it picks up:

- CORS handling via :class:`aiohttp_cors.CorsViewMixin`,
- JSON encoding helpers (``self.json_response`` / ``self.response``),
- Navigator session integration (``await self.session()``),
- The usual ``connect`` / ``close`` DB helpers.

:class:`SSEView` is an **addition**, not a replacement — the existing
:class:`~navigator.services.sse.mixin.SSEMixin` and
:class:`~navigator.services.sse.mixin.SSEEventView` remain untouched for
backward compatibility (spec §8 open question: "coexist").

Usage::

    from navigator.views import SSEView
    from navigator.services.sse.mixin import setup_sse_manager

    async def on_startup(app):
        await setup_sse_manager(app)        # provides app['sse_manager']

    app.router.add_view('/events/{task_id}', SSEView)

To customize behavior, subclass and override
:meth:`SSEView.on_subscribe` (called just before the SSE stream opens)
or :meth:`SSEView._extract_user_id` (to plug in custom auth).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from aiohttp import web
from navconfig.logging import logging

from ..services.sse.manager import SSEManager
from .base import BaseView


class SSEView(BaseView):
    """Class-based View for Server-Sent Events.

    Inherits CORS, session, JSON encoding, and DB helpers from
    :class:`BaseView`. Delegates the actual SSE wire protocol to an
    :class:`SSEManager` instance that must be attached to the aiohttp
    application under the ``'sse_manager'`` key.
    """

    logger = logging.getLogger("navigator.SSEView")

    # ------------------------------------------------------------------
    # SSEManager access (mirrors SSEMixin.sse_manager at line 49-57
    # of services/sse/mixin.py — kept identical for consistency).
    # ------------------------------------------------------------------

    @property
    def sse_manager(self) -> SSEManager:
        """Return the application's :class:`SSEManager`.

        Raises:
            RuntimeError: when ``request.app['sse_manager']`` is not
                configured. Points the caller at
                :func:`navigator.services.sse.mixin.setup_sse_manager`.
        """
        if "sse_manager" not in self.request.app:
            raise RuntimeError(
                "SSE Manager not configured. Add SSE manager to your app: "
                "app['sse_manager'] = SSEManager()"
            )
        return self.request.app["sse_manager"]

    # ------------------------------------------------------------------
    # View handlers
    # ------------------------------------------------------------------

    async def get(self) -> web.StreamResponse:
        """Handle the SSE subscription request.

        Resolves ``task_id`` from the URL match info, extracts a user id
        (hook: :meth:`_extract_user_id`), fires the optional
        :meth:`on_subscribe` hook, then hands off to
        :meth:`SSEManager.subscribe_to_task`.

        Returns:
            The :class:`aiohttp.web.StreamResponse` produced by the SSE
            manager (the long-lived SSE connection).
        """
        task_id = self.request.match_info.get("task_id")
        if not task_id:
            return self.error(
                reason="task_id is required",
                status=400,
            )

        user_id = await self._extract_user_id()
        await self.on_subscribe(self.request, task_id, user_id)

        return await self.sse_manager.subscribe_to_task(
            self.request,
            task_id,
            user_id,
        )

    async def get_stats(self) -> web.Response:
        """Return SSEManager statistics as JSON.

        Small convenience handler — subclasses can route a GET to this
        method by overriding :meth:`get` or by adding a separate view.
        """
        stats = self.sse_manager.get_stats()
        return self.json_response(stats)

    # ------------------------------------------------------------------
    # Broadcast helpers (parity with SSEMixin — callable from other
    # handlers that want to push updates to the same connections).
    # ------------------------------------------------------------------

    async def create_task(
        self,
        task_type: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create an SSE task via the wrapped :class:`SSEManager`."""
        if user_id is None:
            user_id = await self._extract_user_id()
        return await self.sse_manager.create_task_notification(
            task_type=task_type,
            user_id=user_id,
            metadata=metadata,
        )

    async def notify_progress(
        self,
        task_id: str,
        progress_data: Dict[str, Any],
    ) -> int:
        """Broadcast a progress update for *task_id*."""
        return await self.sse_manager.broadcast_task_progress(
            task_id, progress_data
        )

    async def notify_result(
        self,
        task_id: str,
        result_data: Dict[str, Any],
        close_connections: bool = True,
    ) -> int:
        """Broadcast the final result for *task_id*."""
        return await self.sse_manager.broadcast_task_result(
            task_id, result_data, close_connections
        )

    async def notify_error(
        self,
        task_id: str,
        error_data: Dict[str, Any],
        close_connections: bool = True,
    ) -> int:
        """Broadcast an error for *task_id*."""
        return await self.sse_manager.broadcast_task_error(
            task_id, error_data, close_connections
        )

    # ------------------------------------------------------------------
    # Hooks — override in subclasses for custom behavior.
    # ------------------------------------------------------------------

    async def on_subscribe(
        self,
        request: web.Request,
        task_id: str,
        user_id: Optional[str],
    ) -> None:
        """Hook fired just before the SSE stream is opened.

        The default implementation is a no-op. Subclasses can use it to
        perform authorization checks, log the subscription, or record
        metrics. Raise :class:`aiohttp.web.HTTPException` subclasses to
        reject the subscription before it reaches the SSE layer.
        """

    async def _extract_user_id(self) -> Optional[str]:
        """Resolve the user id for the current request.

        The default implementation tries, in order:

        1. A Navigator session via ``await self.session()`` — if the
           session carries ``user_id``, it is returned as a string.
        2. The ``user_id`` query parameter, if present.

        Subclasses can override this to integrate with JWT, OAuth2, or
        other identity schemes.
        """
        try:
            session = await self.session()
        except Exception as exc:  # pragma: no cover — auth layer noise
            self.logger.debug("SSEView session lookup failed: %s", exc)
            session = None

        if session and "user_id" in session:
            return str(session["user_id"])

        if user_id := self.request.query.get("user_id"):
            return user_id

        return None
