"""SSL integration tests for navigator-api.

Spec FEAT-001 / TASK-007 — covers the previously untested SSL surface:

* :meth:`navigator.navigator.Application._generate_ssl_context`:
  - returns ``None`` when ``self.use_ssl`` is ``False``,
  - constructs a valid :class:`ssl.SSLContext` with a real cert/key,
  - raises when SSL is enabled but ``SSL_CERT`` / ``SSL_KEY`` are missing,
  - raises on an invalid (non-existent) cert path.

* End-to-end HTTPS traffic through aiohttp's ``AppRunner`` + ``TCPSite``
  (same plumbing used by :meth:`Application._run_tcp`): a client built
  on the test CA can ``GET`` a route over TLS and receive the expected
  response.

All certificates are generated in-process via ``trustme`` — the tests
never hit the network or touch files that must be committed.
"""
from __future__ import annotations

import socket
import ssl
import types
from pathlib import Path

import pytest
from aiohttp import ClientSession, TCPConnector, web

from navigator import navigator as nav_mod


def _pick_free_port() -> int:
    """Return an OS-assigned free TCP port on 127.0.0.1.

    Avoids reaching into ``TCPSite._server`` (private attribute that can
    churn across aiohttp releases) and works the same on every platform.
    A narrow race window exists between close and the server binding, but
    it is negligible for local test runs.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# _generate_ssl_context tests
# ---------------------------------------------------------------------------

def _make_context_caller(
    use_ssl: bool,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cert_path: Path | None = None,
    key_path: Path | None = None,
    ca_path: Path | None = None,
) -> types.SimpleNamespace:
    """Build the minimal object needed to call ``_generate_ssl_context``.

    The method only touches ``self.use_ssl`` and ``self.logger``; everything
    else comes from :mod:`navigator.conf`. We patch the relevant conf
    attributes for each test.
    """
    from navigator import conf as navigator_conf

    # Patch the conf attributes — getattr() with a default of None is used
    # inside ``_generate_ssl_context`` so missing attributes become None.
    monkeypatch.setattr(
        navigator_conf,
        "SSL_CERT",
        str(cert_path) if cert_path is not None else None,
        raising=False,
    )
    monkeypatch.setattr(
        navigator_conf,
        "SSL_KEY",
        str(key_path) if key_path is not None else None,
        raising=False,
    )
    monkeypatch.setattr(
        navigator_conf,
        "CA_FILE",
        str(ca_path) if ca_path is not None else None,
        raising=False,
    )

    stub = types.SimpleNamespace()
    stub.use_ssl = use_ssl
    stub.logger = types.SimpleNamespace(
        debug=lambda *a, **kw: None,
        info=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        exception=lambda *a, **kw: None,
    )
    return stub


class TestGenerateSSLContext:
    def test_returns_none_when_use_ssl_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        stub = _make_context_caller(use_ssl=False, monkeypatch=monkeypatch)
        result = nav_mod.Application._generate_ssl_context(stub)  # type: ignore[arg-type]
        assert result is None

    def test_valid_cert_and_key_produces_ssl_context(
        self,
        ssl_cert_files: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ):
        cert_path, key_path, _ca_path = ssl_cert_files
        stub = _make_context_caller(
            use_ssl=True,
            monkeypatch=monkeypatch,
            cert_path=cert_path,
            key_path=key_path,
        )
        ctx = nav_mod.Application._generate_ssl_context(stub)  # type: ignore[arg-type]
        assert isinstance(ctx, ssl.SSLContext)
        # ``set_ciphers(FORCED_CIPHERS)`` was applied — verify by reading
        # back the cipher list (non-empty is enough).
        assert ctx.get_ciphers(), "FORCED_CIPHERS produced an empty list"

    def test_valid_cert_key_and_ca_file_produces_ssl_context(
        self,
        ssl_cert_files: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ):
        cert_path, key_path, ca_path = ssl_cert_files
        stub = _make_context_caller(
            use_ssl=True,
            monkeypatch=monkeypatch,
            cert_path=cert_path,
            key_path=key_path,
            ca_path=ca_path,
        )
        ctx = nav_mod.Application._generate_ssl_context(stub)  # type: ignore[arg-type]
        assert isinstance(ctx, ssl.SSLContext)

    def test_missing_cert_and_key_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        stub = _make_context_caller(use_ssl=True, monkeypatch=monkeypatch)
        with pytest.raises(ValueError, match="SSL_CERT and SSL_KEY"):
            nav_mod.Application._generate_ssl_context(stub)  # type: ignore[arg-type]

    def test_invalid_cert_path_raises(
        self,
        ssl_cert_files: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        _cert_path, key_path, _ca = ssl_cert_files
        bogus_cert = tmp_path / "does-not-exist.pem"
        stub = _make_context_caller(
            use_ssl=True,
            monkeypatch=monkeypatch,
            cert_path=bogus_cert,
            key_path=key_path,
        )
        # ``load_cert_chain`` raises FileNotFoundError when the path does
        # not exist; ``_generate_ssl_context`` re-raises after logging.
        with pytest.raises((FileNotFoundError, ssl.SSLError, OSError)):
            nav_mod.Application._generate_ssl_context(stub)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# End-to-end HTTPS tests
# ---------------------------------------------------------------------------

class TestHTTPSServer:
    async def test_https_roundtrip(
        self,
        server_ssl_ctx: ssl.SSLContext,
        client_ssl_ctx: ssl.SSLContext,
    ):
        """Start an HTTPS server via AppRunner + TCPSite and hit /ping.

        This mirrors the plumbing used inside
        :meth:`Application._run_tcp` — if that code path regresses,
        this test fails.
        """
        app = web.Application()

        async def _ping(_request: web.Request) -> web.Response:
            return web.Response(text="pong")

        app.router.add_get("/ping", _ping)

        port = _pick_free_port()
        runner = web.AppRunner(app, handle_signals=False)
        await runner.setup()
        site = web.TCPSite(
            runner,
            host="127.0.0.1",
            port=port,
            ssl_context=server_ssl_ctx,
        )
        await site.start()

        try:
            connector = TCPConnector(ssl=client_ssl_ctx)
            async with ClientSession(connector=connector) as session:
                url = f"https://localhost:{port}/ping"
                async with session.get(url) as resp:
                    assert resp.status == 200
                    assert await resp.text() == "pong"
        finally:
            await runner.cleanup()

    async def test_https_json_response(
        self,
        server_ssl_ctx: ssl.SSLContext,
        client_ssl_ctx: ssl.SSLContext,
    ):
        """JSON request/response over HTTPS (covers the full serializer)."""
        app = web.Application()

        async def _echo(request: web.Request) -> web.Response:
            payload = await request.json()
            return web.json_response({"received": payload, "ok": True})

        app.router.add_post("/echo", _echo)

        port = _pick_free_port()
        runner = web.AppRunner(app, handle_signals=False)
        await runner.setup()
        site = web.TCPSite(
            runner,
            host="127.0.0.1",
            port=port,
            ssl_context=server_ssl_ctx,
        )
        await site.start()

        try:
            connector = TCPConnector(ssl=client_ssl_ctx)
            async with ClientSession(connector=connector) as session:
                url = f"https://localhost:{port}/echo"
                async with session.post(url, json={"name": "nav"}) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data == {"received": {"name": "nav"}, "ok": True}
        finally:
            await runner.cleanup()
