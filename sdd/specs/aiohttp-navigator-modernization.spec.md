# Feature Specification: aiohttp Navigator Modernization

**Feature ID**: FEAT-001
**Date**: 2026-04-20
**Author**: Jesus Lara / Claude
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

navigator-api is a batteries-included web framework based on aiohttp. While focus shifted to navigator-auth, ai-parrot, and other packages, navigator-api accumulated technical debt:

1. **Misused Cython** in modules with zero performance benefit (exceptions, utils/functions, utils/types)
2. **Missing Cython interfaces** (`.pxd`/`.pyi`) for `types.pyx`, `handlers/base.pyx`
3. **Dead code**: `SafeDict` and `Singleton` in Cython are shadowed by `datamodel` imports; `_run_legacy()` is unused
4. **aiohttp version floor** at `>=3.10.0` instead of modern `>=3.13.0`
5. **Bug**: `_run_unix()` uses undefined variable `path` instead of `unix_path` (line 673)
6. **Heavyweight base deps**: `cartopy`, `matplotlib`, `pyarrow`, `psycopg2-binary`, `google-cloud-*`, `Faker` in base install but only used by optional actions or not at all
7. **No SSL test coverage** despite `_generate_ssl_context()` support
8. **Incomplete SSE View**: `SSEEventView` doesn't inherit from navigator's `BaseView`

### Goals
- Remove Cython from modules where it provides no performance benefit (exceptions, utils/functions)
- Benchmark `handlers/base.pyx` and `utils/types.pyx` (Singleton) with `pyperf` — data-driven keep/convert decision with 10% speedup threshold
- Add `.pxd`/`.pyi` stubs for all remaining Cython modules
- Fix the `_run_unix()` bug and remove the dead `_run_legacy()` path
- Bump aiohttp minimum to `>=3.13.0`
- Move heavyweight dependencies to optional extras
- Add SSL integration tests
- Create a proper `SSEView` class inheriting from `BaseView`

### Non-Goals (explicitly out of scope)
- Replacing custom `URL` class with `yarl.URL` (future investigation)
- Full `aiohttp-cors` replacement (stays as-is, part of aiolibs)
- Architectural redesign of the handler/application hierarchy
- Breaking changes to the public API

---

## 2. Architectural Design

### Overview

This is a modernization/cleanup effort, not a new feature. The work decomposes into 6 independent modules that modify existing code rather than introducing new architecture. The only new component is the `SSEView` class, which wraps the existing `SSEManager`.

### Component Diagram
```
Module 1: Cython Benchmarks
    └──→ Module 2: Cython Cleanup (informed by benchmark results)
              └──→ Module 6: Cython Interface Stubs

Module 3: AppRunner Modernization (independent)
    navigator/navigator.py
        ├── fix _run_unix() bug
        ├── remove _run_legacy()
        └── remove use_legacy_runner flag

Module 4: Dependency Cleanup (independent)
    pyproject.toml
        ├── bump aiohttp >=3.13.0
        ├── move optional deps to extras
        ├── remove unused deps
        └── add lazy imports

Module 5: SSE View (independent, depends on stable BaseView)
    navigator/views/sse.py (new)
        └── SSEView(BaseView) wraps SSEManager

Module 7: SSL Tests (independent)
    tests/test_ssl.py (new)
        └── self-signed cert fixtures + server tests
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator/exceptions/exceptions.pyx` | replaces | Cython → pure Python, same API surface |
| `navigator/utils/functions.pyx` | removes | `get_logger` inlined or moved; `SafeDict` from datamodel |
| `navigator/utils/types.pyx` | benchmark-dependent | Remove if Singleton benchmark shows <10% gain |
| `navigator/handlers/base.pyx` | benchmark-dependent | Convert to Python or add .pyi stubs based on results |
| `navigator/navigator.py` | modifies | Fix bug, remove legacy runner |
| `navigator/views/base.py:BaseView` | extends | New SSEView inherits from BaseView |
| `navigator/services/sse/manager.py:SSEManager` | uses | SSEView delegates to SSEManager |
| `navigator/services/sse/mixin.py:SSEMixin` | preserves | Backward compat, SSEView is an addition |
| `pyproject.toml` | modifies | Dependency restructuring |
| `setup.py` | modifies | Remove deleted Cython extensions |

### Data Models
No new data models. Existing `SSEConnection` dataclass in `navigator/services/sse/manager.py:18` is reused.

### New Public Interfaces
```python
# navigator/views/sse.py (new file)
class SSEView(BaseView):
    """Class-based View for SSE with full navigator integration.

    Inherits CORS, session, JSON encoding from BaseView.
    Wraps SSEManager for connection lifecycle.
    """

    async def get(self) -> web.StreamResponse:
        """Handle SSE subscription requests."""
        ...

    @property
    def sse_manager(self) -> SSEManager:
        """Access the app-level SSE manager."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Cython Benchmarks
- **Path**: `benchmarks/cython_benchmarks.py` (new)
- **Responsibility**: Benchmark `BaseAppHandler.__init__()` + `CreateApp()` in Cython vs pure Python equivalent. Benchmark `Singleton.__call__()` Cython vs `datamodel.typedefs.singleton.Singleton`. Produce a report with timing comparison.
- **Depends on**: nothing (runs first)
- **Output**: Benchmark results that inform Module 2 decisions. If <10% speedup, the Cython module is marked for conversion.

### Module 2: Cython Cleanup
- **Path**: `navigator/exceptions/exceptions.py` (replaces `.pyx`), `navigator/utils/functions.py` (replaces `.pyx`), `navigator/utils/types.pyx` (conditionally removed), `navigator/handlers/base.pyx` (conditionally converted), `setup.py`
- **Responsibility**: Convert `exceptions.pyx` → pure Python (same API). Remove `utils/functions.pyx` (get_logger to inline pure Python, SafeDict already from datamodel). Conditionally remove `utils/types.pyx` and convert `handlers/base.pyx` based on Module 1 results. Update `setup.py` to remove deleted extensions.
- **Depends on**: Module 1 (benchmark results)

### Module 3: AppRunner Modernization
- **Path**: `navigator/navigator.py`
- **Responsibility**: Fix `_run_unix()` bug (`path` → `unix_path` at lines 673, 680). Remove `_run_legacy()` method (lines 839-902). Remove `use_legacy_runner` flag handling in `run()` (line 800-801). Clean up related imports if any.
- **Depends on**: nothing (independent)

### Module 4: Dependency Cleanup
- **Path**: `pyproject.toml`, `navigator/actions/google/maps.py`
- **Responsibility**: Bump `aiohttp[speedups]>=3.13.0`. Create optional extras: `[google]` (cartopy, matplotlib, polyline, google-cloud-core, google-cloud-storage), `[scraping]` (beautifulsoup4, proxylists, PySocks, aiosocks), `[testing]` (Faker). Remove from base deps: `psycopg2-binary`, `pyarrow`. Convert top-level imports in `navigator/actions/google/maps.py` to lazy imports with clear error messages.
- **Depends on**: nothing (independent)

### Module 5: SSE View
- **Path**: `navigator/views/sse.py` (new), `navigator/views/__init__.py`
- **Responsibility**: Create `SSEView` class inheriting from `BaseView` (line 596 of `navigator/views/base.py`). SSEView integrates with `SSEManager` (from `navigator/services/sse/manager.py`), provides CORS/session/JSON support via BaseView inheritance, and exposes a developer-friendly API. Existing `SSEMixin` and `SSEEventView` in `services/sse/mixin.py` are preserved for backward compatibility. Export `SSEView` from `navigator/views/__init__.py`.
- **Depends on**: nothing (BaseView API is stable)

### Module 6: Cython Interface Stubs
- **Path**: `navigator/types.pxd` (new), `navigator/types.pyi` (new), `navigator/handlers/base.pyi` (new or updated)
- **Responsibility**: Add `.pxd` and `.pyi` interface files for all Cython modules that remain after Module 2. This includes at minimum `types.pyx` and `applications/base.pyx` (which already has a `.pyi`). If `handlers/base.pyx` stays Cython, create its `.pyi`. Verify existing `applications/base.pyi` is accurate and complete.
- **Depends on**: Module 2 (must know which modules stay Cython)

### Module 7: SSL Tests
- **Path**: `tests/test_ssl.py` (new), `tests/conftest.py` (new or extended)
- **Responsibility**: Add pytest fixtures for self-signed certificate generation (using `trustme` or `cryptography`). Test SSL server startup via `_run_tcp()` with SSL context. Test `_generate_ssl_context()` with valid/invalid cert paths. Test HTTPS request/response cycle.
- **Depends on**: nothing (independent)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_nav_exception_hierarchy` | Module 2 | All exception classes instantiate with correct state codes |
| `test_nav_exception_str` | Module 2 | `str(NavException("msg"))` returns expected format |
| `test_nav_exception_get` | Module 2 | `.get()` returns message |
| `test_nav_exception_stacktrace` | Module 2 | stacktrace kwarg is preserved |
| `test_exception_subclasses` | Module 2 | Each subclass (InvalidArgument, ConfigError, etc.) has correct default message and state |
| `test_get_logger` | Module 2 | `get_logger()` returns configured logger |
| `test_singleton_benchmark` | Module 1 | Cython Singleton vs datamodel Singleton timing |
| `test_base_app_handler_benchmark` | Module 1 | Cython BaseAppHandler vs pure Python timing |
| `test_run_unix_path_param` | Module 3 | `_run_unix()` uses `unix_path` correctly |
| `test_no_legacy_runner` | Module 3 | `_run_legacy` method does not exist |
| `test_lazy_import_google` | Module 4 | `navigator.actions.google.maps` produces clear error without cartopy |
| `test_dependency_extras` | Module 4 | Optional extras are resolvable |

### Integration Tests
| Test | Description |
|---|---|
| `test_ssl_server_startup` | Start HTTPS server with self-signed cert, make request |
| `test_ssl_context_generation` | `_generate_ssl_context()` with valid cert/key paths |
| `test_ssl_context_disabled` | Returns None when `USE_SSL=False` |
| `test_ssl_invalid_cert` | Proper error on bad cert path |
| `test_sse_view_subscribe` | SSEView handles GET subscription request |
| `test_sse_view_cors` | SSEView responds to CORS preflight |
| `test_sse_view_lifecycle` | Full connect → progress → result → disconnect cycle |

### Test Data / Fixtures
```python
@pytest.fixture
def ssl_cert(tmp_path):
    """Generate self-signed cert/key pair for testing."""
    # Use trustme or cryptography to generate ephemeral certs
    ...

@pytest.fixture
async def sse_app(aiohttp_client):
    """App with SSEManager and SSEView configured."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] All exception classes work identically in pure Python as they did in Cython (same API, same state codes, same str representation)
- [ ] `utils/functions.pyx` and `utils/functions.pxd` are deleted; `get_logger` works from pure Python
- [ ] Benchmark report exists for `handlers/base.pyx` and `Singleton` with clear speedup measurements
- [ ] Cython modules kept/converted based on benchmark evidence (10% threshold)
- [ ] All remaining Cython modules have `.pxd` and `.pyi` interface files
- [ ] `_run_unix()` bug is fixed (uses `unix_path` parameter)
- [ ] `_run_legacy()` method is removed from `navigator/navigator.py`
- [ ] `aiohttp[speedups]>=3.13.0` in pyproject.toml
- [ ] `psycopg2-binary` and `pyarrow` removed from base dependencies
- [ ] `cartopy`, `matplotlib`, `polyline`, `google-cloud-*` in `[google]` extra
- [ ] `beautifulsoup4`, `proxylists`, `PySocks`, `aiosocks` in `[scraping]` extra
- [ ] `Faker` moved to `[dev]` or `[testing]` extra
- [ ] Top-level imports in `navigator/actions/google/maps.py` converted to lazy imports
- [ ] SSL integration tests pass with self-signed certs
- [ ] `SSEView` class inherits from `BaseView`, integrates with `SSEManager`
- [ ] Existing `SSEMixin` and `SSEEventView` still work (backward compat)
- [ ] No breaking changes to existing public API
- [ ] `setup.py` extensions list matches surviving Cython modules
- [ ] All existing tests still pass

---

## 6. Codebase Contract

> **CRITICAL -- Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# Exception system
from navigator.exceptions import NavException, InvalidArgument, ConfigError, UserNotFound, Unauthorized, InvalidAuth, FailedAuth, AuthExpired, ValidationError
# verified: navigator/exceptions/__init__.py:5-15

# Views
from navigator.views import BaseHandler, BaseView, DataView, ModelView, ModelHandler, FormModel
# verified: navigator/views/__init__.py:7-10

# SSE
from navigator.services.sse.manager import SSEManager, SSEConnection
# verified: navigator/services/sse/manager.py:36,18
from navigator.services.sse.mixin import SSEMixin, SSEEventView
# verified: navigator/services/sse/mixin.py:12,175
from navigator.responses import sse_response, EventSourceResponse
# verified: navigator/responses.py:14,18-21

# Utils (re-exported from datamodel)
from navigator.utils import SafeDict, Singleton
# verified: navigator/utils/__init__.py:1-2 (imports from datamodel)
from datamodel.typedefs.types import SafeDict, AttrDict, NullDefault
# verified: navigator/utils/__init__.py:2
from datamodel.typedefs.singleton import Singleton
# verified: navigator/utils/__init__.py:1

# Types
from navigator.types import WebApp, URL, HTTPMethod, HTTPRequest, HTTPResponse, HTTPHandler, HTTPRoute
# verified: navigator/types.pyx:12-23,26

# Handlers
from navigator.handlers import BaseAppHandler
# verified: navigator/handlers/__init__.py:7
from navigator.handlers.types import AppHandler, AppConfig
# verified: navigator/handlers/types.py:21,108

# Applications
from navigator.applications.base import BaseApplication
# verified: navigator/applications/base.pyx:20 (cimports BaseAppHandler)

# Logging
from navconfig.logging import logging, loglevel
# verified: used in navigator/views/base.py:25, navigator/applications/base.pyx:7

# JSON
from datamodel.parsers.json import json_encoder, json_decoder, JSONContent
# verified: navigator/views/base.py:19-23

# Session
from navigator_session import get_session
# verified: navigator/views/base.py:26

# CORS
import aiohttp_cors
from aiohttp_cors import setup as cors_setup, ResourceOptions
# verified: navigator/handlers/base.pyx:9-10
```

### Existing Class Signatures
```python
# navigator/exceptions/exceptions.pyx
cdef class NavException(Exception):
    state: int = 0  # line 10
    def __init__(self, str message, int state = 0, **kwargs)  # line 12
    # kwargs: stacktrace (optional)
    def __str__(self)  # line 21, returns f"{__name__}: {self.message}"
    def get(self)  # line 24, returns self.message
# Subclasses (all take optional str message):
#   InvalidArgument(state=406) line 28
#   ConfigError(state=500) line 33
#   ValidationError(state=410) line 39
#   UserNotFound(state=404) line 45
#   Unauthorized(state=401) line 50
#   InvalidAuth(state=401) line 55
#   FailedAuth(state=403) line 60
#   AuthExpired(state=410) line 65
#   ActionError(state=400) line 70

# navigator/handlers/base.pyx
cdef class BaseAppHandler:  # line 20
    _middleware: list  # line 26
    enable_static: bool  # line 27
    staticdir: str  # line 28
    config: Callable  # line 30
    def __init__(self, context: dict, app_name: str = None, evt: asyncio.AbstractEventLoop = None)  # line 32
    def CreateApp(self) -> WebApp  # line 72
    def _set_config(self, app: WebApp, conf: Callable, key_name: str = 'config')  # line 101
    def setup_cors(self)  # line 123
    def configure(self)  # line 144
    def add_routes(self, routes: list)  # line 160
    def add_view(self, route: str, view: Callable)  # line 173
    def event_loop(self) -> asyncio.AbstractEventLoop  # line 180
    # Properties:
    App -> WebApp  # line 183-185
    Name -> str  # line 187-189
    # Async signals:
    async def background_tasks(self, app: WebApp)  # line 192 (cleanup_ctx)
    async def on_prepare(self, request, response)  # line 203
    async def pre_cleanup(self, app)  # line 209
    async def on_cleanup(self, app)  # line 215
    async def on_startup(self, app)  # line 221
    async def on_shutdown(self, app)  # line 227
    async def app_startup(self, app: WebApp, connection: Callable)  # line 234

# navigator/applications/base.pyx
cdef class BaseApplication:  # line 20
    def __init__(self, handler=None, title='', contact='', description='NAVIGATOR APP', evt=None, **kwargs)  # line 22
    def get_app(self) -> WebApp  # line 52
    def setup_app(self) -> WebApp  # line 55
    def event_loop(self)  # line 58
    def __setitem__(self, k, v)  # line 61
    def __getitem__(self, k)  # line 64
    def __repr__(self)  # line 67
    def active_extensions(self) -> list  # line 70
    def setup(self) -> WebApp  # line 73

# navigator/utils/types.pyx
cdef class Singleton(type):  # line 4
    cdef dict _instances  # line 11
    def __call__(cls, *args, **kwargs)  # line 13
    cdef object __new__(cls, args, kwargs)  # line 21

# navigator/utils/functions.pyx
def get_logger(str logger_name)  # line 7 — wraps logging.getLogger + setLevel
cdef class SafeDict(dict):  # line 17
    def __missing__(self, str key)  # line 24 — returns "{" + key + "}"

# navigator/types.pyx
cdef class URL:  # line 26
    cdef str value, scheme, path, host, port, netloc, query, fragment  # lines 27-34
    cdef dict params  # line 35
    cdef bool is_absolute  # line 36
    def __init__(self, str value)  # line 41
    cpdef URL change_scheme(self, str scheme)  # line 96
    cpdef URL change_host(self, str host)  # line 109

# navigator/views/base.py
class BaseHandler(ABC):  # line 42
    _allowed_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]  # line 46
    def __init__(self, *args, **kwargs)  # line 48
    def post_init(self, *args, **kwargs)  # line 56
    async def session(self)  # line 66
    def response(self, response="", status=200, ...) -> web.Response  # line 101
    def json_response(self, response=None, ...) -> JSONResponse  # line 121
    def critical(self, reason=None, ...) -> web.Response  # line 144
    def error(self, ...)  # further down

class BaseView(aiohttp_cors.CorsViewMixin, BaseHandler, web.View):  # line 596
    cors_config = {"*": ResourceOptions(...)}  # lines 598-606
    def __init__(self, request, *args, **kwargs)  # line 608
    @classmethod
    def setup(cls, app, route)  # line 613
    async def connect(self, request)  # line 631
    async def close(self)  # line 645

# navigator/services/sse/manager.py
@dataclass
class SSEConnection:  # line 18
    task_id: str
    response: Any
    request: web.Request
    connection_id: str  # auto-generated UUID

class SSEManager:  # line 36
    def __init__(self)  # line 56
    async def start_cleanup_task(self)  # line 63
    async def stop(self)  # line 68
    async def create_task_notification(self, task_type, user_id=None, metadata=None) -> str  # line 81
    async def subscribe_to_task(self, request, task_id, user_id=None) -> web.StreamResponse  # line 110
    async def broadcast_task_progress(self, task_id, progress_data) -> int  # line 175
    async def broadcast_task_result(self, task_id, result_data, close_connections=True) -> int  # line 203
    async def broadcast_task_error(self, task_id, error_data, close_connections=True) -> int  # line 244
    def get_stats(self) -> Dict[str, Any]  # line 377

# navigator/services/sse/mixin.py
class SSEMixin:  # line 12
    @property
    def sse_manager(self) -> SSEManager  # line 49
    async def create_task(self, task_type, user_id=None, metadata=None) -> str  # line 59
    async def notify_progress(self, task_id, progress_data) -> int  # line 86
    async def notify_result(self, task_id, result_data, close_connections=True) -> int  # line 103
    async def notify_error(self, task_id, error_data, close_connections=True) -> int  # line 124

class SSEEventView(SSEMixin):  # line 175
    async def get(self) -> web.StreamResponse  # line 184

# navigator/handlers/types.py
class AppHandler(BaseAppHandler):  # line 21
    # Inherits from BaseAppHandler (Cython cdef class)
    def __init__(self, context, app_name=None, evt=None)  # line 36
    def CreateApp(self) -> web.Application  # line 52
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SSEView` | `BaseView` | class inheritance | `navigator/views/base.py:596` |
| `SSEView` | `SSEManager` | `request.app['sse_manager']` | `navigator/services/sse/mixin.py:52-57` |
| `SSEView` | `aiohttp_cors.CorsViewMixin` | via BaseView MRO | `navigator/views/base.py:596` |
| Pure Python exceptions | `navigator/exceptions/__init__.py` | import (same names) | `navigator/exceptions/__init__.py:5-15` |
| `setup.py` | Cython extensions list | `Extension()` definitions | `setup.py:15-51` |
| `pyproject.toml` | dependency list | `[project.dependencies]` | `pyproject.toml:53-90` |
| `AppHandler` | `BaseAppHandler` | Python `import` (not `cimport`) | `navigator/handlers/types.py:18` |
| `BaseApplication` | `BaseAppHandler` | Cython `cimport` | `navigator/applications/base.pyx:17` |

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.views.SSEView`~~ -- does not exist yet (to be created in Module 5)
- ~~`navigator/views/sse.py`~~ -- does not exist yet (to be created in Module 5)
- ~~`navigator/types.pxd`~~ -- does not exist (to be created in Module 6)
- ~~`navigator/types.pyi`~~ -- does not exist (to be created in Module 6)
- ~~`navigator/handlers/base.pyi`~~ -- does not exist (to be created in Module 6)
- ~~`tests/test_ssl.py`~~ -- does not exist (to be created in Module 7)
- ~~`tests/conftest.py`~~ -- does not exist (to be created in Module 7)
- ~~`benchmarks/`~~ -- directory does not exist (to be created in Module 1)
- ~~`navigator.utils.functions.SafeDict` at runtime~~ -- the Cython .pyx defines it but `navigator/utils/__init__.py` imports from `datamodel` instead, shadowing the Cython version
- ~~`navigator.utils.types.Singleton` at runtime~~ -- same shadowing: `utils/__init__.py` imports from `datamodel`
- ~~`aiohttp` built-in CORS middleware~~ -- does not exist in aiohttp core; CORS handled by `aiohttp-cors`
- ~~`Faker` usage anywhere in navigator~~ -- not imported in any `.py` or `.pyx` file
- ~~`psycopg2` direct usage in navigator~~ -- not imported anywhere (transitive via asyncdb only)
- ~~`pyarrow` direct usage in navigator~~ -- not imported anywhere
- ~~`navigator.navigator.Navigator._run_legacy`~~ -- will not exist after Module 3

### Critical cimport Chain
`applications/base.pyx` line 17 uses `from ..handlers.base cimport BaseAppHandler`. If `handlers/base.pyx` is converted to pure Python (based on benchmarks), `applications/base.pyx` must also be converted or its import changed to a regular Python import. This is the only `cimport` dependency on `BaseAppHandler`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Exception conversion: preserve exact `__init__` signatures, `state` attribute, `__str__` format, and `get()` method
- Lazy imports pattern: `try: import X; except ImportError: raise ImportError("Install navigator-api[extra] for X support")`
- SSEView: follow the same `cors_config` pattern as `BaseView` (line 598-606)
- Benchmarks: use `pyperf` for reproducible micro-benchmarks with warm-up and calibration
- Pure Python `get_logger`: identical signature `def get_logger(logger_name: str)` returning configured logger

### Known Risks / Gotchas
- **cimport chain**: `applications/base.pyx:17` uses `cimport BaseAppHandler`. Converting `handlers/base.pyx` to Python requires also converting `applications/base.pyx` or changing the import. Both files must be handled together.
- **Compiled .so artifacts**: Users upgrading will have stale `.so` files from deleted Cython modules. The pure Python `.py` files take precedence only if the `.so` is removed. Document this in release notes or add a post-install cleanup.
- **Top-level imports in google/maps.py**: `cartopy` and `matplotlib` are imported at module level (lines 14-17). Moving to extras requires converting to lazy imports, which changes the error timing from import-time to call-time.
- **`aiohttp-sse` stability**: Last release was 2024. The package is stable but unmaintained. If issues arise with aiohttp 3.13, may need to vendor or fork.
- **redis override**: `pyproject.toml` line 178-180 has `[tool.uv] override-dependencies = ["redis==5.2.1"]`. Must verify this is still needed with current navigator-session.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp[speedups]` | `>=3.13.0` | Bumped minimum for modern AppRunner features |
| `pyperf` | `>=2.6.0` | Cython vs Python micro-benchmarking (dev only) |
| `trustme` | `>=1.0.0` | SSL test certificate generation (test only) |
| `aiohttp-sse` | `>=2.2.0` | SSE support (already a dependency) |
| `aiohttp-cors` | `==0.8.1` | CORS support (unchanged) |

---

## 8. Open Questions

- [ ] Should `navigator/types.pyx` URL class remain Cython long-term, or plan a `yarl.URL` migration as a follow-up? -- *Owner: Jesus Lara*
- [ ] Is `sockjs>=0.11.0` still needed? Only imported conditionally in `navigator.py:19`. -- *Owner: Jesus Lara*
- [ ] Should `aiohttp-sse` be vendored/forked given no new releases since 2024? -- *Owner: Jesus Lara*
- [ ] Is the `redis==5.2.1` override-dependency in `[tool.uv]` still needed? -- *Owner: Jesus Lara*
- [ ] Should the new `SSEView` replace `SSEEventView` or coexist? -- *Owner: Jesus Lara*
- [ ] `navigator/actions/google/maps.py` does top-level imports of `cartopy`/`matplotlib` -- confirm no startup-time side effects from lazy import conversion. -- *Owner: Jesus Lara*

---

## Worktree Strategy

- **Default isolation**: `mixed` (some tasks parallelizable)
- **Parallel streams**:
  - Module 1 (Benchmarks) runs FIRST — results inform Module 2
  - Module 3 (AppRunner), Module 4 (Dependencies), Module 5 (SSE View), Module 7 (SSL Tests) are fully independent — can run in parallel worktrees
  - Module 2 (Cython Cleanup) depends on Module 1
  - Module 6 (Cython Stubs) depends on Module 2
- **Cross-feature dependencies**: None. navigator-api has no in-flight specs.
- **Recommended execution order**:
  1. Module 1 (benchmarks)
  2. Modules 2, 3, 4, 5, 7 in parallel (after benchmarks complete)
  3. Module 6 last (needs Module 2 decisions)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Jesus Lara / Claude | Initial draft from brainstorm |
