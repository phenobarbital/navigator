"""Shared pytest fixtures.

Spec FEAT-001 / TASK-007 — currently hosts SSL certificate fixtures
built with :mod:`trustme`. Fixtures are session-scoped: certificate
generation is the slowest part of trustme (it computes a private key),
so we do it exactly once per test process.
"""
from __future__ import annotations

import ssl
import tempfile
from pathlib import Path
from typing import Iterator

import pytest
import trustme


@pytest.fixture(scope="session")
def ca() -> trustme.CA:
    """Session-wide ephemeral Certificate Authority."""
    return trustme.CA()


@pytest.fixture(scope="session")
def server_cert(ca: trustme.CA) -> trustme.LeafCert:
    """Leaf cert valid for ``localhost`` / ``127.0.0.1``."""
    return ca.issue_cert("localhost", "127.0.0.1")


@pytest.fixture(scope="session")
def server_ssl_ctx(server_cert: trustme.LeafCert) -> ssl.SSLContext:
    """Server-side :class:`ssl.SSLContext` with the ephemeral cert loaded."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_cert.configure_cert(ctx)
    return ctx


@pytest.fixture(scope="session")
def client_ssl_ctx(ca: trustme.CA) -> ssl.SSLContext:
    """Client-side :class:`ssl.SSLContext` that trusts the ephemeral CA."""
    ctx = ssl.create_default_context()
    ca.configure_trust(ctx)
    return ctx


@pytest.fixture(scope="session")
def ssl_cert_files(
    ca: trustme.CA,
    server_cert: trustme.LeafCert,
) -> Iterator[tuple[Path, Path, Path]]:
    """Write (cert_pem, key_pem, ca_pem) to temp files and yield their paths.

    Used by :meth:`Application._generate_ssl_context` tests that need
    real filesystem paths rather than SSLContext objects.
    """
    with tempfile.TemporaryDirectory(prefix="navigator-ssl-") as tmp:
        tmp_path = Path(tmp)
        cert_path = tmp_path / "server.pem"
        key_path = tmp_path / "server.key"
        ca_path = tmp_path / "ca.pem"

        # ``private_key_and_cert_chain_pem`` / ``private_key_pem`` are the
        # trustme 1.x API. We write cert + key as separate files because
        # ``ssl.SSLContext.load_cert_chain`` accepts them that way.
        cert_path.write_bytes(
            b"".join(blob.bytes() for blob in server_cert.cert_chain_pems)
        )
        key_path.write_bytes(server_cert.private_key_pem.bytes())
        ca_path.write_bytes(ca.cert_pem.bytes())

        yield cert_path, key_path, ca_path
