"""Tests for the FEAT-004 QWorker background tasker stack.

These tests cover:

1. ``QWorkerTasker`` unit tests (all three remote modes, failure paths,
   missing-qworker path, tracker integration) — QClient is mocked via a
   fake ``qw.client`` module injected into ``sys.modules``.
2. ``TaskWrapper`` with ``execution_mode="remote"`` — QWorkerTasker is
   mocked so we don't touch qworker at all.
3. ``BackgroundService.submit()`` remote kwarg passthrough.
4. Package wiring (``navigator.background`` imports cleanly, QWorkerTasker
   is re-exported).

No tests require a running qworker server — the real ``qw.client`` module
has heavy transitive deps (flowtask, redis, etc.), so we never let it be
imported inside tests. A lightweight fake module stands in.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from navigator.background import (
    BackgroundService,
    JobTracker,
    TaskWrapper,
)
from navigator.background.taskers.qworker import QWorkerTasker
from navigator.background.wrappers import VALID_EXECUTION_MODES


# =====================================================================
# Helpers
# =====================================================================


def _install_fake_qw_client(monkeypatch, qclient_mock):
    """Install a fake ``qw.client`` module so that the lazy import inside
    ``QWorkerTasker.__init__`` resolves to our mock without triggering the
    real ``qw`` package's heavy transitive imports (flowtask, redis, ...).
    """
    fake_module = types.ModuleType("qw.client")
    fake_module.QClient = MagicMock(return_value=qclient_mock)
    # Also provide a minimal ``qw`` parent package if missing.
    if "qw" not in sys.modules or not hasattr(sys.modules["qw"], "__path__"):
        qw_pkg = types.ModuleType("qw")
        qw_pkg.__path__ = []  # mark as package for import machinery
        monkeypatch.setitem(sys.modules, "qw", qw_pkg)
    monkeypatch.setitem(sys.modules, "qw.client", fake_module)
    return fake_module.QClient  # the MagicMock class


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def mock_qclient():
    """A MagicMock QClient instance whose async methods return realistic payloads."""
    client = MagicMock(name="QClient")
    client.run = AsyncMock(return_value={"answer": 42})
    client.queue = AsyncMock(
        return_value={"status": "Queued", "task": "fn", "message": "ok"}
    )
    client.publish = AsyncMock(
        return_value={"status": "Queued", "task": "fn", "message": "stream-1"}
    )
    return client


@pytest.fixture
def fake_qclient_class(monkeypatch, mock_qclient):
    """Install the fake ``qw.client`` module and return the class mock that
    ``QWorkerTasker.__init__`` will call."""
    return _install_fake_qw_client(monkeypatch, mock_qclient)


@pytest.fixture
def tasker(fake_qclient_class):
    """A ``QWorkerTasker`` whose underlying QClient is the fixture mock."""
    return QWorkerTasker(worker_list=[("localhost", 8181)], timeout=3)


@pytest.fixture
async def tracker():
    """A fresh in-memory JobTracker with no reaper running."""
    return JobTracker(ttl_seconds=60, reap_interval=9999)


# =====================================================================
# QWorkerTasker — construction
# =====================================================================


class TestQWorkerTaskerInit:
    def test_creates_with_defaults(self, fake_qclient_class):
        t = QWorkerTasker()
        assert t.default_mode == "run"
        assert t.timeout == 5
        assert t.worker_list is None
        fake_qclient_class.assert_called_once_with(
            worker_list=None, timeout=5
        )

    def test_creates_with_custom_workers(self, fake_qclient_class):
        t = QWorkerTasker(
            worker_list=[("127.0.0.1", 9000)],
            timeout=11,
            default_mode="queue",
        )
        assert t.default_mode == "queue"
        assert t.timeout == 11
        assert t.worker_list == [("127.0.0.1", 9000)]
        fake_qclient_class.assert_called_once_with(
            worker_list=[("127.0.0.1", 9000)], timeout=11
        )

    def test_invalid_default_mode(self, fake_qclient_class):
        with pytest.raises(ValueError, match="Invalid default_mode"):
            QWorkerTasker(default_mode="teleport")

    def test_missing_qworker_raises(self, monkeypatch):
        """If ``qw.client`` cannot be imported, construction raises a
        helpful ``ImportError`` mentioning the install command."""
        # Remove any cached qw.client entry and make the import fail.
        monkeypatch.delitem(sys.modules, "qw.client", raising=False)

        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "qw.client":
                raise ImportError("No module named 'qw.client'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        with pytest.raises(ImportError) as excinfo:
            QWorkerTasker()
        assert "navigator-api[qworker]" in str(excinfo.value)


# =====================================================================
# QWorkerTasker — dispatch modes
# =====================================================================


class TestQWorkerTaskerDispatch:
    @pytest.mark.asyncio
    async def test_run_mode_returns_result(self, tasker, mock_qclient):
        async def my_fn(x):  # pragma: no cover — body sent remotely
            return x * 2

        result = await tasker.dispatch(my_fn, 21, remote_mode="run")
        assert result == {"answer": 42}
        mock_qclient.run.assert_awaited_once()
        _, kwargs = mock_qclient.run.call_args
        # QWorkerTasker passes use_wrapper=False for run mode.
        assert kwargs.get("use_wrapper") is False

    @pytest.mark.asyncio
    async def test_queue_mode_returns_ack(self, tasker, mock_qclient):
        async def my_fn():  # pragma: no cover
            return None

        result = await tasker.dispatch(my_fn, remote_mode="queue")
        assert result["status"] == "Queued"
        mock_qclient.queue.assert_awaited_once()
        _, kwargs = mock_qclient.queue.call_args
        assert kwargs.get("use_wrapper") is True

    @pytest.mark.asyncio
    async def test_publish_mode_returns_ack(self, tasker, mock_qclient):
        async def my_fn():  # pragma: no cover
            return None

        result = await tasker.dispatch(my_fn, remote_mode="publish")
        assert result["status"] == "Queued"
        assert result["message"] == "stream-1"
        mock_qclient.publish.assert_awaited_once()
        _, kwargs = mock_qclient.publish.call_args
        assert kwargs.get("use_wrapper") is True

    @pytest.mark.asyncio
    async def test_falls_back_to_default_mode(self, fake_qclient_class, mock_qclient):
        """When ``remote_mode`` is omitted, ``default_mode`` is used."""
        t = QWorkerTasker(default_mode="publish")
        await t.dispatch(lambda: None)
        mock_qclient.publish.assert_awaited_once()
        mock_qclient.queue.assert_not_awaited()
        mock_qclient.run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_remote_mode(self, tasker):
        with pytest.raises(ValueError, match="Invalid remote_mode"):
            await tasker.dispatch(lambda: None, remote_mode="teleport")

    @pytest.mark.asyncio
    async def test_run_exception_propagates(self, tasker, mock_qclient):
        mock_qclient.run.side_effect = RuntimeError("worker blew up")
        with pytest.raises(RuntimeError, match="worker blew up"):
            await tasker.dispatch(lambda: None, remote_mode="run")


# =====================================================================
# QWorkerTasker — tracker integration
# =====================================================================


class TestQWorkerTaskerTracker:
    @pytest.mark.asyncio
    async def test_run_updates_tracker_to_done(
        self, tasker, mock_qclient, tracker
    ):
        from navigator.background.tracker import JobRecord

        rec = await tracker.create_job(JobRecord(name="t"))
        await tasker.dispatch(
            lambda: None,
            remote_mode="run",
            tracker=tracker,
            task_uuid=rec.task_id,
        )
        updated = await tracker.status(rec.task_id)
        assert updated.status == "done"
        assert updated.result == {"answer": 42}

    @pytest.mark.asyncio
    async def test_queue_updates_tracker_to_queued_remote(
        self, tasker, mock_qclient, tracker
    ):
        from navigator.background.tracker import JobRecord

        rec = await tracker.create_job(JobRecord(name="t"))
        await tasker.dispatch(
            lambda: None,
            remote_mode="queue",
            tracker=tracker,
            task_uuid=rec.task_id,
        )
        updated = await tracker.status(rec.task_id)
        assert updated.status == "queued_remote"

    @pytest.mark.asyncio
    async def test_publish_updates_tracker_to_queued_remote(
        self, tasker, mock_qclient, tracker
    ):
        from navigator.background.tracker import JobRecord

        rec = await tracker.create_job(JobRecord(name="t"))
        await tasker.dispatch(
            lambda: None,
            remote_mode="publish",
            tracker=tracker,
            task_uuid=rec.task_id,
        )
        updated = await tracker.status(rec.task_id)
        assert updated.status == "queued_remote"

    @pytest.mark.asyncio
    async def test_exception_updates_tracker_to_failed(
        self, tasker, mock_qclient, tracker
    ):
        from navigator.background.tracker import JobRecord

        mock_qclient.run.side_effect = RuntimeError("boom")
        rec = await tracker.create_job(JobRecord(name="t"))
        with pytest.raises(RuntimeError):
            await tasker.dispatch(
                lambda: None,
                remote_mode="run",
                tracker=tracker,
                task_uuid=rec.task_id,
            )
        updated = await tracker.status(rec.task_id)
        assert updated.status == "failed"
        assert "RuntimeError" in (updated.error or "")

    @pytest.mark.asyncio
    async def test_no_tracker_is_noop(self, tasker, mock_qclient):
        """dispatch() without a tracker must not crash."""
        result = await tasker.dispatch(lambda: None, remote_mode="run")
        assert result == {"answer": 42}

    @pytest.mark.asyncio
    async def test_close_is_noop(self, tasker):
        await tasker.close()  # must not raise


# =====================================================================
# TaskWrapper — remote mode
# =====================================================================


class TestTaskWrapperRemote:
    def test_valid_execution_modes_include_remote(self):
        assert "remote" in VALID_EXECUTION_MODES

    def test_accepts_remote_mode(self):
        tw = TaskWrapper(lambda: None, execution_mode="remote")
        assert tw.execution_mode == "remote"
        # Defaults applied
        assert tw.remote_mode == "run"
        assert tw.worker_list is None
        assert tw.remote_timeout == 5
        assert tw._tasker is None

    def test_remote_kwargs_are_stripped_from_kwargs(self):
        """remote_mode / worker_list / remote_timeout must NOT leak into
        ``self.kwargs`` (which gets forwarded to the function)."""
        tw = TaskWrapper(
            lambda: None,
            execution_mode="remote",
            remote_mode="queue",
            worker_list=[("h", 1)],
            remote_timeout=9,
            extra="forward-me",
        )
        assert tw.remote_mode == "queue"
        assert tw.worker_list == [("h", 1)]
        assert tw.remote_timeout == 9
        assert tw.kwargs == {"extra": "forward-me"}

    def test_same_loop_unaffected(self):
        tw = TaskWrapper(lambda: None, execution_mode="same_loop")
        assert tw.execution_mode == "same_loop"
        assert tw._tasker is None

    def test_thread_unaffected(self):
        tw = TaskWrapper(lambda: None, execution_mode="thread")
        assert tw.execution_mode == "thread"

    @pytest.mark.asyncio
    async def test_remote_run_delegates_to_tasker(self, monkeypatch):
        mock_tasker = MagicMock(name="QWorkerTasker")
        mock_tasker.dispatch = AsyncMock(return_value={"answer": 99})
        monkeypatch.setattr(
            "navigator.background.taskers.qworker.QWorkerTasker",
            MagicMock(return_value=mock_tasker),
        )

        def my_fn(a, b):  # pragma: no cover — never actually executed
            return a + b

        tw = TaskWrapper(my_fn, 1, 2, execution_mode="remote")
        result = await tw()
        assert result == {"status": "done", "result": {"answer": 99}}
        mock_tasker.dispatch.assert_awaited_once()
        args, kwargs = mock_tasker.dispatch.call_args
        assert args[0] is my_fn
        assert args[1:] == (1, 2)
        assert kwargs["remote_mode"] == "run"

    @pytest.mark.asyncio
    async def test_remote_queue_returns_queued_remote(self, monkeypatch):
        mock_tasker = MagicMock()
        mock_tasker.dispatch = AsyncMock(
            return_value={"status": "Queued", "task": "x", "message": "m"}
        )
        monkeypatch.setattr(
            "navigator.background.taskers.qworker.QWorkerTasker",
            MagicMock(return_value=mock_tasker),
        )
        tw = TaskWrapper(
            lambda: None, execution_mode="remote", remote_mode="queue"
        )
        result = await tw()
        assert result["status"] == "queued_remote"
        assert result["result"]["status"] == "Queued"

    @pytest.mark.asyncio
    async def test_remote_publish_returns_queued_remote(self, monkeypatch):
        mock_tasker = MagicMock()
        mock_tasker.dispatch = AsyncMock(
            return_value={"status": "Queued", "task": "x", "message": "s-1"}
        )
        monkeypatch.setattr(
            "navigator.background.taskers.qworker.QWorkerTasker",
            MagicMock(return_value=mock_tasker),
        )
        tw = TaskWrapper(
            lambda: None, execution_mode="remote", remote_mode="publish"
        )
        result = await tw()
        assert result["status"] == "queued_remote"

    @pytest.mark.asyncio
    async def test_remote_exception_returns_failed(self, monkeypatch):
        mock_tasker = MagicMock()
        mock_tasker.dispatch = AsyncMock(side_effect=RuntimeError("remote boom"))
        monkeypatch.setattr(
            "navigator.background.taskers.qworker.QWorkerTasker",
            MagicMock(return_value=mock_tasker),
        )
        tw = TaskWrapper(lambda: None, execution_mode="remote")
        result = await tw()
        assert result["status"] == "failed"
        assert "remote boom" in result["error"]


# =====================================================================
# BackgroundService — remote submit (end-to-end with real queue)
# =====================================================================


async def _remote_fn():  # pragma: no cover — body never executed
    return "noop"


async def _same_loop_fn():
    return "hello"


def _build_remote_app(mock_tasker):
    """Build a minimal aiohttp app with a BackgroundService. Remote dispatch
    goes through a mocked ``QWorkerTasker`` so no network / qworker is needed.
    """
    app = web.Application()
    service = BackgroundService(app)

    async def submit_remote(request: web.Request) -> web.Response:
        job = await service.submit(
            _remote_fn,
            execution_mode="remote",
            remote_mode="publish",
            worker_list=[("h", 1)],
            remote_timeout=7,
        )
        return web.json_response({"task_id": job.task_id})

    async def submit_local(request: web.Request) -> web.Response:
        job = await service.submit(_same_loop_fn)
        return web.json_response({"task_id": job.task_id})

    async def status_handler(request: web.Request) -> web.Response:
        task_id = request.match_info["task_id"]
        rec = await service.tracker.status(task_id)
        if rec is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"task_id": rec.task_id, "status": rec.status})

    app.router.add_post("/remote", submit_remote)
    app.router.add_post("/local", submit_local)
    app.router.add_get("/tasks/{task_id}", status_handler)
    return app, service


class TestBackgroundServiceRemote:
    @pytest.mark.asyncio
    async def test_submit_remote_forwards_kwargs(self, monkeypatch):
        import asyncio

        mock_tasker = MagicMock(name="QWorkerTasker")
        mock_tasker.dispatch = AsyncMock(return_value={"ok": True})
        # Patch the class so TaskWrapper's lazy import returns our mock.
        monkeypatch.setattr(
            "navigator.background.taskers.qworker.QWorkerTasker",
            MagicMock(return_value=mock_tasker),
        )

        app, service = _build_remote_app(mock_tasker)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/remote")
            assert resp.status == 200
            # Let the queue process the TaskWrapper.
            await asyncio.sleep(0.3)

            mock_tasker.dispatch.assert_awaited()
            _, kwargs = mock_tasker.dispatch.call_args
            assert kwargs["remote_mode"] == "publish"

    @pytest.mark.asyncio
    async def test_submit_default_still_same_loop(self):
        """Plain submit() without execution_mode still defaults to same_loop
        and runs the function locally."""
        import asyncio

        app, service = _build_remote_app(mock_tasker=None)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/local")
            assert resp.status == 200
            body = await resp.json()
            task_id = body["task_id"]
            # Poll for the task to finish.
            for _ in range(20):
                rec = await service.tracker.status(task_id)
                if rec and rec.status in ("done", "failed"):
                    break
                await asyncio.sleep(0.1)
            rec = await service.tracker.status(task_id)
            assert rec.status == "done"
            assert rec.result == "hello"


# =====================================================================
# Package wiring
# =====================================================================


class TestPackageWiring:
    def test_import_background_clean(self):
        import navigator.background  # noqa: F401 — must not raise

    def test_qworkertasker_from_background(self):
        from navigator.background import QWorkerTasker as QWT
        # With qworker installed (dev env), QWT is the real class.
        assert QWT is not None
        assert QWT is QWorkerTasker

    def test_qworkertasker_from_taskers(self):
        from navigator.background.taskers import QWorkerTasker as QWT
        assert QWT is QWorkerTasker

    def test_taskers_all_contains_qworkertasker(self):
        import navigator.background.taskers as tk
        assert "QWorkerTasker" in tk.__all__
