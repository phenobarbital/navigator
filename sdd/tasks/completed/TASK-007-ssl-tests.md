# TASK-007: SSL Integration Tests

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: sdd-worker

---

## Context

Navigator supports SSL via `_generate_ssl_context()` in `navigator/navigator.py`, but there are zero tests covering this functionality. This task adds SSL integration tests using self-signed certificates generated at test time.

Implements: Spec Module 7 (SSL Tests).

---

## Scope

- Add `trustme>=1.0.0` to `[project.optional-dependencies.test]` in `pyproject.toml`
- Create `tests/conftest.py` with SSL certificate fixtures (using `trustme`)
- Create `tests/test_ssl.py` with integration tests:
  - SSL context generation from valid cert/key
  - SSL context returns None when `USE_SSL=False`
  - SSL context error on invalid cert path
  - HTTPS server startup via `_run_tcp()` with SSL context
  - HTTPS request/response cycle

**NOT in scope**: Modifying `_generate_ssl_context()`. Changing production SSL code. Unix socket SSL.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/conftest.py` | CREATE | SSL fixtures and shared test config |
| `tests/test_ssl.py` | CREATE | SSL integration tests |
| `pyproject.toml` | MODIFY | Add trustme to test deps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# SSL context generation:
import ssl  # stdlib
# navigator/navigator.py — SSL context method (need to verify exact location)

# aiohttp test utilities:
from aiohttp.test_utils import AioHTTPTestCase  # available via aiohttp
from aiohttp import web  # verified: navigator/navigator.py:7

# Configuration:
from navigator.conf import USE_SSL, SSL_CERT, SSL_KEY, CA_FILE
# verified: navigator/conf.py (need to check exact exports)
```

### Existing Signatures to Use
```python
# navigator/navigator.py — SSL context generation
# Method: _generate_ssl_context() at approximately line 467-505
# Returns: ssl.SSLContext or None
# Logic:
#   - Checks USE_SSL flag from config (returns None if False)
#   - Loads CA file if configured
#   - Creates context with ssl.Purpose.CLIENT_AUTH
#   - Loads certificate chain from SSL_CERT and SSL_KEY
#   - Sets forced ciphers via FORCED_CIPHERS constant

# navigator/navigator.py:564 — _run_tcp with SSL support
async def _run_tcp(
    self, app, host=None, port=None, ssl_context=None, handle_signals=False, **kwargs
) -> None:
    # Creates web.AppRunner, web.TCPSite with ssl_context parameter

# FORCED_CIPHERS constant (approximately line 465):
FORCED_CIPHERS = "ECDH+AESGCM:DH+AESGCM:ECDH+AES256:..."
```

### Does NOT Exist
- ~~`tests/conftest.py`~~ — does not exist yet
- ~~`tests/test_ssl.py`~~ — does not exist yet
- ~~Any existing SSL tests~~ — none found in the codebase
- ~~`navigator.navigator.Navigator._generate_ssl_context` as a public method~~ — it's a private method (underscore prefix)

---

## Implementation Notes

### Pattern to Follow — trustme fixtures
```python
# tests/conftest.py
import pytest
import ssl
import trustme


@pytest.fixture(scope="session")
def ca():
    """Create a Certificate Authority for testing."""
    return trustme.CA()


@pytest.fixture(scope="session")
def server_ssl_ctx(ca):
    """Create server SSL context with test certificate."""
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ca.issue_cert("localhost", "127.0.0.1").configure_cert(server_ctx)
    ca.configure_trust(server_ctx)
    return server_ctx


@pytest.fixture(scope="session")
def client_ssl_ctx(ca):
    """Create client SSL context trusting test CA."""
    client_ctx = ssl.create_default_context()
    ca.configure_trust(client_ctx)
    return client_ctx
```

### Key Constraints
- Use `trustme` for certificate generation — no committed cert files
- Tests must work in CI (no real certificates, no network access needed)
- The `_generate_ssl_context()` method reads from navconfig settings — tests need to mock/override those settings
- Use `aiohttp.test_utils` for server lifecycle management in tests
- Tests should be in `tests/` directory (matching `pyproject.toml:testpaths`)

### References in Codebase
- `navigator/navigator.py:467-505` — `_generate_ssl_context()` method
- `navigator/navigator.py:564-636` — `_run_tcp()` with SSL
- `navigator/conf.py:66-82` — SSL configuration variables
- `pyproject.toml:138-146` — existing `[test]` dependencies

---

## Acceptance Criteria

- [ ] `trustme>=1.0.0` added to `[project.optional-dependencies.test]`
- [ ] `tests/conftest.py` exists with SSL certificate fixtures
- [ ] `tests/test_ssl.py` exists with at least 4 SSL tests
- [ ] Tests pass: `pytest tests/test_ssl.py -v`
- [ ] Tests work without real SSL certificates (trustme generates ephemeral ones)
- [ ] Tests cover: context creation, disabled SSL, invalid cert, HTTPS request/response

---

## Test Specification

```python
# tests/test_ssl.py
import pytest
import ssl
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase


class TestSSLContextGeneration:
    def test_ssl_context_with_valid_certs(self, server_ssl_ctx):
        """SSL context is created with valid test certificates."""
        assert isinstance(server_ssl_ctx, ssl.SSLContext)

    def test_ssl_context_disabled(self):
        """Returns None when USE_SSL is False."""
        # Mock USE_SSL = False and call _generate_ssl_context
        ...

    def test_ssl_context_invalid_cert_path(self):
        """Raises error with invalid certificate path."""
        ...


class TestSSLServer:
    async def test_https_server_startup(self, aiohttp_client, server_ssl_ctx, client_ssl_ctx):
        """HTTPS server starts and responds to requests."""
        app = web.Application()
        app.router.add_get('/ping', lambda r: web.Response(text='pong'))

        client = await aiohttp_client(app, ssl=server_ssl_ctx)
        resp = await client.get('/ping', ssl=client_ssl_ctx)
        assert resp.status == 200
        text = await resp.text()
        assert text == 'pong'

    async def test_https_request_response_cycle(self, aiohttp_client, server_ssl_ctx, client_ssl_ctx):
        """Full HTTPS request/response with JSON body."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `navigator/navigator.py` lines 467-505 for `_generate_ssl_context()`
2. **Read** `navigator/conf.py` for SSL config variables
3. **Activate venv**: `source .venv/bin/activate`
4. **Install trustme**: `uv pip install trustme`
5. **Add trustme** to `pyproject.toml` test deps
6. **Create** `tests/conftest.py` with fixtures
7. **Create** `tests/test_ssl.py` with tests
8. **Run tests**: `pytest tests/test_ssl.py -v`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-20
**Commit**: `feat-001-aiohttp-navigator-modernization` / 9bd8b96

**What shipped:**

- `tests/conftest.py` (new) — session-scoped fixtures powered by
  :mod:`trustme`:
  - ``ca``               ephemeral Certificate Authority
  - ``server_cert``      leaf cert for ``localhost``/``127.0.0.1``
  - ``server_ssl_ctx``   server-side :class:`ssl.SSLContext`
  - ``client_ssl_ctx``   client-side context trusting the test CA
  - ``ssl_cert_files``   writes cert/key/CA PEMs to a tempdir so tests
                         that need filesystem paths (the
                         ``_generate_ssl_context`` ones) can point at
                         real files.

- `tests/test_ssl.py` (new, 7 test cases):
  - ``TestGenerateSSLContext``
      - returns ``None`` when ``self.use_ssl`` is ``False``.
      - builds a valid ``ssl.SSLContext`` from cert + key, and applies
        ``FORCED_CIPHERS`` (verified via ``get_ciphers()``).
      - same, with an additional CA file.
      - raises ``ValueError('SSL_CERT and SSL_KEY...')`` when the
        required config is missing.
      - raises ``FileNotFoundError``/``OSError``/``ssl.SSLError`` on a
        non-existent cert path.
  - ``TestHTTPSServer`` — end-to-end via ``web.AppRunner`` +
    ``web.TCPSite(ssl_context=...)``, i.e. the exact plumbing used by
    ``Application._run_tcp``:
      - plain ``GET /ping`` → 200 ``pong``
      - ``POST /echo`` with a JSON body → round-trips through
        ``aiohttp.web.json_response``.

  The unit tests for ``_generate_ssl_context`` call the method directly
  on a ``types.SimpleNamespace`` stub and monkey-patch
  ``navigator.conf.SSL_CERT`` / ``SSL_KEY`` / ``CA_FILE``. This avoids
  instantiating the full ``Application``, which would drag in navconfig,
  an event loop, signal handlers, etc. — a deliberately thin harness
  that makes the tests fast and CI-friendly.

- `pyproject.toml` — adds ``trustme>=1.0.0`` to
  ``[project.optional-dependencies.test]``.

**No production SSL code was modified.** The task's explicit "NOT in
scope" list is honored.

**Verification:**

- `pytest tests/test_ssl.py -v` → **7 passed**.
- `pytest tests/` → **53 passed** (32 exceptions + 14 SSE view + 7 SSL).
- Tests run offline — trustme generates ephemeral certs in-process,
  no committed ``.pem`` files, no external network needed.

**Deviations from spec**: none. The spec's "test specification" block
was a sketch; the concrete tests that shipped cover the same five
behaviors (valid context, disabled SSL, invalid cert, HTTPS startup,
HTTPS request/response) plus two extras (CA-file branch, POST/JSON).
