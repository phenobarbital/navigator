# -*- coding: utf-8 -*-
"""QWorkerTasker — remote task dispatcher backed by qworker.

This module wraps :class:`qw.client.QClient` and provides a :meth:`dispatch`
method that can send a callable to a remote qworker pool in three modes:

* ``run``      — send and wait for result via ``QClient.run()``.
* ``queue``    — fire-and-forget via TCP ``QClient.queue()``.
* ``publish``  — fire-and-forget via Redis Streams ``QClient.publish()``.

``qworker`` is a heavy optional dependency, so it is **lazy-imported** inside
the constructor. If ``qworker`` is not installed, constructing a
``QWorkerTasker`` raises :class:`ImportError` with installation instructions,
but *importing* this module does not fail.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple, List

from navconfig.logging import logging


# Do NOT import qw at module level — it pulls in heavy dependencies
# (flowtask, redis, cloudpickle, etc.). Import happens lazily inside
# ``QWorkerTasker.__init__``.


class QWorkerTasker:
    """Dispatches background tasks to a remote qworker pool.

    ``QWorkerTasker`` is a thin adapter around :class:`qw.client.QClient`.
    It routes a callable to one of three QClient entrypoints depending on
    the ``remote_mode`` argument supplied to :meth:`dispatch` (or the
    ``default_mode`` supplied at construction time).

    Tracker integration: if a :class:`~navigator.background.tracker.JobTracker`
    and ``task_uuid`` are provided to :meth:`dispatch`, the tracker is updated
    to ``running`` before dispatch and to ``done`` / ``failed`` (run mode) or
    a custom ``queued_remote`` status (queue / publish modes) afterwards.

    Args:
        worker_list: Optional list of ``(host, port)`` tuples describing the
            qworker pool. If ``None``, QClient falls back to its own
            discovery / Redis / env-based worker resolution.
        timeout: Per-call TCP timeout in seconds passed to ``QClient``.
        default_mode: Fallback remote mode (``"run"``, ``"queue"`` or
            ``"publish"``) used when :meth:`dispatch` is called without an
            explicit ``remote_mode`` argument.

    Raises:
        ImportError: If the optional ``qworker`` package is not installed.
        ValueError: If ``default_mode`` is not one of the valid modes.
    """

    _VALID_MODES: Tuple[str, ...] = ("run", "queue", "publish")
    _QUEUED_REMOTE_STATUS: str = "queued_remote"

    def __init__(
        self,
        worker_list: Optional[List[Tuple[str, int]]] = None,
        timeout: int = 5,
        default_mode: str = "run",
    ) -> None:
        # Lazy-import QClient: qworker is an optional dependency.
        try:
            from qw.client import QClient  # noqa: WPS433 (runtime import)
        except ImportError as exc:
            raise ImportError(
                "qworker is required for remote task dispatch. "
                "Install it with: pip install navigator-api[qworker]"
            ) from exc

        if default_mode not in self._VALID_MODES:
            raise ValueError(
                f"Invalid default_mode '{default_mode}'. "
                f"Must be one of: {self._VALID_MODES!r}."
            )

        self._client = QClient(worker_list=worker_list, timeout=timeout)
        self.default_mode: str = default_mode
        self.worker_list = worker_list
        self.timeout: int = timeout
        self.logger = logging.getLogger("NAV.Queue.QWorkerTasker")

    async def dispatch(
        self,
        fn: Callable,
        *args: Any,
        remote_mode: Optional[str] = None,
        tracker: Any = None,
        task_uuid: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Send ``fn`` to a remote qworker instance.

        Args:
            fn: Callable to execute remotely. Must be picklable by
                ``cloudpickle`` (no closures over unpicklable state).
            *args: Positional arguments passed to ``fn`` on the remote worker.
            remote_mode: One of ``"run"``, ``"queue"`` or ``"publish"``. If
                ``None``, falls back to ``self.default_mode``.
            tracker: Optional :class:`JobTracker` to update with status
                transitions. Updates are best-effort — failures to update
                the tracker are logged but do not abort dispatch.
            task_uuid: Job id (string or UUID) to key tracker updates by.
            **kwargs: Additional keyword arguments forwarded to ``fn``.

        Returns:
            For ``run`` mode: the result returned by the remote worker.
            For ``queue`` / ``publish`` modes: the dict returned by
            ``QClient.queue()`` / ``QClient.publish()`` (shape:
            ``{"status": "Queued", "task": ..., "message": ...}``).

        Raises:
            ValueError: If ``remote_mode`` (or ``default_mode``) is invalid.
            Exception: Any exception raised by the remote execution is
                propagated to the caller. The tracker (if provided) is
                transitioned to ``failed`` before the exception is re-raised.
        """
        mode = remote_mode or self.default_mode
        if mode not in self._VALID_MODES:
            raise ValueError(
                f"Invalid remote_mode '{mode}'. "
                f"Must be one of: {self._VALID_MODES!r}."
            )

        # Mark tracker as running before dispatch (best-effort).
        await self._set_running(tracker, task_uuid)

        try:
            if mode == "run":
                # Wait for and return the remote result.
                # use_wrapper=False: caller wants the raw result, not
                # qworker's wrapper envelope.
                result = await self._client.run(
                    fn, *args, use_wrapper=False, **kwargs
                )
                await self._set_done(tracker, task_uuid, result)
                return result

            if mode == "queue":
                # Fire-and-forget via TCP. Returns {"status": "Queued", ...}.
                response = await self._client.queue(
                    fn, *args, use_wrapper=True, **kwargs
                )
                await self._set_queued_remote(tracker, task_uuid, response)
                return response

            # mode == "publish"
            # Fire-and-forget via Redis Streams.
            response = await self._client.publish(
                fn, *args, use_wrapper=True, **kwargs
            )
            await self._set_queued_remote(tracker, task_uuid, response)
            return response

        except Exception as exc:  # noqa: BLE001 — re-raised below
            self.logger.error(
                "QWorkerTasker dispatch failed for %s (mode=%s): %s",
                getattr(fn, "__name__", repr(fn)),
                mode,
                exc,
            )
            await self._set_failed(tracker, task_uuid, exc)
            raise

    async def close(self) -> None:
        """Release any resources held by the tasker.

        :class:`QClient` creates per-call TCP connections and does not expose
        a persistent connection that needs closing, so this method is a
        no-op today. It exists as an extensibility hook and so callers can
        always ``await tasker.close()`` without a capability check.
        """
        self.logger.debug("QWorkerTasker.close() — no persistent resources to release")

    # ------------------------------------------------------------------
    # Tracker helpers (best-effort — never let tracker errors abort dispatch)
    # ------------------------------------------------------------------
    async def _set_running(self, tracker: Any, task_uuid: Any) -> None:
        if tracker is None or task_uuid is None:
            return
        try:
            await tracker.set_running(task_uuid)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Tracker set_running failed: %s", exc)

    async def _set_done(self, tracker: Any, task_uuid: Any, result: Any) -> None:
        if tracker is None or task_uuid is None:
            return
        try:
            await tracker.set_done(task_uuid, result)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Tracker set_done failed: %s", exc)

    async def _set_failed(
        self, tracker: Any, task_uuid: Any, exc: Exception
    ) -> None:
        if tracker is None or task_uuid is None:
            return
        try:
            await tracker.set_failed(task_uuid, exc)
        except Exception as tracker_exc:  # noqa: BLE001
            self.logger.warning("Tracker set_failed failed: %s", tracker_exc)

    async def _set_queued_remote(
        self, tracker: Any, task_uuid: Any, response: Any
    ) -> None:
        """Set tracker status to ``queued_remote`` (queue / publish modes).

        Because qworker has no built-in completion callback for fire-and-forget
        modes, the tracker will stay at ``queued_remote`` forever unless the
        caller implements their own transition.
        """
        if tracker is None or task_uuid is None:
            return
        try:
            async with tracker._lock:  # type: ignore[attr-defined]
                rec = tracker._jobs.get(task_uuid)  # type: ignore[attr-defined]
                if rec is not None:
                    rec.status = self._QUEUED_REMOTE_STATUS
                    rec.result = response
        except AttributeError:
            # Tracker is not a standard JobTracker (no _lock/_jobs); fall back
            # to the public API and mark the job as done with the response.
            try:
                await tracker.set_done(task_uuid, response)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Tracker set_done (fallback for queued_remote) failed: %s", exc
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Tracker queued_remote update failed: %s", exc)
