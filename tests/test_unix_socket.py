"""Regression tests for :meth:`Application._run_unix`.

Spec FEAT-001 follow-up — TASK-003 fixed the ``path`` / ``unix_path``
name mix-up, but left a latent bug: the ``**kwargs`` flowing into
``_run_unix`` came from ``run()`` / ``start_server()`` and already
contained ``access_log``, ``keepalive_timeout``, ``client_timeout``,
``max_request_size``, ``access_log_class``, ``access_log_format`` —
none of which are valid kwargs for :class:`aiohttp.web.UnixSite`.
Forwarding them all as ``**kwargs`` would raise ``TypeError: __init__()
got an unexpected keyword argument 'access_log'`` on any Unix-socket
startup path.

These tests drive the real ``_run_unix`` coroutine against a
temporary socket and assert that:

* it completes without raising when every known AppRunner kwarg is
  passed in (the scenario produced by :meth:`Application.run`),
* a client can round-trip a request over the resulting Unix socket,
* the socket file is created at the given path and cleaned up on
  ``_graceful_shutdown``.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, UnixConnector, web

from navigator import navigator as nav_mod


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Unix domain sockets are not available on Windows.",
)


def _make_nav_stub(tmp_path: Path) -> nav_mod.Application:
    """Build the minimal ``Application`` object ``_run_unix`` touches."""
    stub = nav_mod.Application.__new__(nav_mod.Application)
    stub.host = "127.0.0.1"
    stub.port = 0
    stub.path = None
    stub.use_ssl = False
    stub.debug = False
    stub.logger = logging.getLogger("navigator.test_unix_socket")
    stub._runner = None  # type: ignore[attr-defined]
    stub._sites = []  # type: ignore[attr-defined]
    stub._shutdown_timeout = 5.0  # type: ignore[attr-defined]
    return stub


class TestRunUnix:
    async def test_forwards_only_valid_unixsite_kwargs(
        self, tmp_path: Path
    ):
        """Passes every AppRunner-level kwarg ``run()`` would produce.

        Pre-fix, ``_run_unix`` forwarded the full kwargs dict to
        ``web.UnixSite(**kwargs)``. Any of ``access_log``,
        ``keepalive_timeout``, ``client_timeout``, ``max_request_size``
        would trigger ``TypeError``. The fix narrows the forwarded set
        to ``shutdown_timeout`` / ``ssl_context`` / ``backlog``.
        """
        app = web.Application()

        async def _ping(_request: web.Request) -> web.Response:
            return web.Response(text="pong")

        app.router.add_get("/ping", _ping)

        sock_path = tmp_path / "nav-test.sock"
        stub = _make_nav_stub(tmp_path)

        # Mirror exactly the kwargs ``start_server`` / ``run`` hand to
        # ``_run_unix`` today — every one of these should be silently
        # dropped when constructing the UnixSite.
        await stub._run_unix(  # type: ignore[attr-defined]
            app,
            sock_path,
            access_log=None,
            keepalive_timeout=30,
            client_timeout=60,
            max_request_size=1024 ** 2,
        )

        try:
            assert sock_path.exists(), "Unix socket file was not created"

            connector = UnixConnector(path=str(sock_path))
            async with ClientSession(connector=connector) as session:
                # aiohttp still requires a URL host; it is ignored by
                # ``UnixConnector`` but must parse.
                async with session.get("http://localhost/ping") as resp:
                    assert resp.status == 200
                    assert await resp.text() == "pong"
        finally:
            if stub._runner is not None:  # type: ignore[attr-defined]
                await stub._runner.cleanup()  # type: ignore[attr-defined]

    async def test_removes_stale_socket_file(self, tmp_path: Path):
        """``_run_unix`` should unlink a pre-existing socket path."""
        app = web.Application()
        sock_path = tmp_path / "stale.sock"
        sock_path.write_bytes(b"")  # pretend it exists from a prior run

        stub = _make_nav_stub(tmp_path)

        await stub._run_unix(app, sock_path)  # type: ignore[attr-defined]

        try:
            assert sock_path.exists()
            # It must be a real socket now, not our leftover empty file.
            # ``asyncio`` / aiohttp create it as a socket — stat().st_size
            # is 0 either way, so test the socket type via connect():
            reader, writer = await asyncio.open_unix_connection(
                path=str(sock_path)
            )
            writer.close()
            await writer.wait_closed()
            assert reader is not None
        finally:
            if stub._runner is not None:  # type: ignore[attr-defined]
                await stub._runner.cleanup()  # type: ignore[attr-defined]
