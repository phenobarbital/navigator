# Brainstorm: aiohttp Navigator Modernization

**Date**: 2026-04-20
**Author**: Jesus Lara / Claude
**Status**: exploration
**Recommended Option**: Option A (augmented with targeted Cython benchmarks)

---

## Problem Statement

navigator-api is a batteries-included web framework based on aiohttp, providing django-style application abstractions, class-based views with integrated CORS, sub-apps, extensions, and navconfig integration. While focus shifted to navigator-auth, ai-parrot, and other packages, navigator-api has fallen behind:

- **Misused Cython**: Several modules (exceptions, utils/functions, utils/types) are compiled with Cython despite providing zero performance benefit — pure Python class hierarchies, logging wrappers, and singleton metaclasses that run once at startup.
- **Missing Cython interfaces**: `types.pyx` and others lack `.pxd`/`.pyi` files, breaking IDE support and downstream `cimport`.
- **Dead code**: `SafeDict` in `utils/functions.pyx` is shadowed by the `datamodel` import in `utils/__init__.py`. `Singleton` in `utils/types.pyx` is shadowed by `datamodel.typedefs.singleton.Singleton`. Legacy runner (`_run_legacy`) is unused.
- **aiohttp version gap**: Current floor is `>=3.10.0` but latest stable is 3.13.x with significant improvements to AppRunner, middleware, and request handling.
- **Bug**: `_run_unix()` at `navigator/navigator.py:673` references undefined variable `path` instead of parameter `unix_path`.
- **Heavyweight base dependencies**: `cartopy`, `matplotlib`, `pyarrow`, `psycopg2-binary`, `google-cloud-*`, `Faker`, `beautifulsoup4`, `proxylists`, `polyline` are hard dependencies but only used by optional actions or not at all.
- **No SSL tests**: SSL support exists in `_generate_ssl_context()` but has no test coverage.
- **SSE View incomplete**: `SSEEventView` exists in `services/sse/mixin.py` but doesn't inherit from navigator's `BaseHandler`/`BaseView`, missing CORS, JSON encoding, and session integration.

**Who is affected**: Developers building applications with navigator-api; the framework's install size and dependency resolution time affects all users.

## Constraints & Requirements

- Must not break existing applications using navigator-api public API
- Cython is NOT being removed from the project — only from modules where it provides no performance gain
- Modules that remain in Cython must get proper `.pxd` and `.pyi` interface files
- aiohttp minimum version bumped to `>=3.13.0`
- `aiohttp-cors` stays (part of aiolibs, released March 2025)
- Custom `URL` class in `types.pyx` stays as-is pending future investigation of `yarl.URL` replacement
- All changes must pass existing tests plus new SSL tests
- Dependency cleanup must not break lazy-imported optional features

---

## Options Explored

### Option A: Targeted Modernization (Surgical Cleanup)

Address each issue individually with minimal blast radius. Convert only the Cython modules with zero performance benefit, fix bugs, clean dependencies, bump aiohttp, add SSL tests, and create proper SSE View class.

✅ **Pros:**
- Low risk: each change is independently testable
- Preserves Cython where it could potentially matter (handlers/base, applications/base, types)
- Clear, reviewable PRs — one concern per task
- No architectural changes, just modernization

❌ **Cons:**
- Doesn't address deeper architectural issues (e.g., the URL class wrapping Python's urlparse negates most Cython gains)
- Multiple tasks that must be coordinated

📊 **Effort:** Medium (10-14 tasks, straightforward conversions + targeted benchmarks)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp[speedups]>=3.13.0` | Core framework | Bumped from >=3.10.0 |
| `aiohttp-sse>=2.2.0` | SSE support | Already a dependency |
| `aiohttp-cors==0.8.1` | CORS | Stays, released Mar 2025 |
| `Cython>=3.0.11` | Build | Stays for remaining .pyx |
| `pytest-aiohttp` | Testing | For SSL integration tests |
| `pyperf` | Micro-benchmarking | Cython vs pure Python for handlers/base and Singleton |

🔗 **Existing Code to Reuse:**
- `navigator/services/sse/manager.py` — Full SSEManager, reuse as backend for new SSEView
- `navigator/services/sse/mixin.py` — SSEMixin patterns, refactor into proper View
- `navigator/views/base.py` — BaseHandler/BaseView as parent for SSEView
- `navigator/navigator.py:564-684` — AppRunner code (fix unix bug, remove legacy)
- `navigator/exceptions/exceptions.pyx` — Convert to pure Python, same API

---

### Option B: Deep Cython Audit + Modernization

Same as Option A but includes a full Cython performance audit: benchmark every `.pyx` module, decide keep/convert based on measured data, and add `.pxd`/`.pyi` for all kept modules. Also investigate replacing the custom `URL` class.

✅ **Pros:**
- Data-driven Cython decisions
- Could reveal unexpected hotspots worth keeping in Cython
- More thorough long-term

❌ **Cons:**
- Significantly more effort for benchmarking infrastructure
- URL class replacement investigation adds scope and risk
- Could delay the straightforward fixes

📊 **Effort:** High (12-18 tasks, includes benchmarking setup)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyperf` | Micro-benchmarking | For Cython vs pure Python comparison |
| `yarl` | URL parsing | Already transitive dep via aiohttp, for URL investigation |
| All from Option A | Same | Same |

🔗 **Existing Code to Reuse:**
- All from Option A
- `navigator/types.pyx` — URL class to benchmark against yarl.URL

---

### Option C: Minimal Fix (Bug Fixes + Dependency Only)

Only fix the critical bug (`_run_unix` variable name), bump aiohttp version, and clean up dependencies. Defer Cython changes, SSE View, and SSL tests to a later cycle.

✅ **Pros:**
- Very low effort and risk
- Immediate value: smaller install, fixed bug, newer aiohttp
- Quick release

❌ **Cons:**
- Doesn't address the Cython misuse or missing interfaces
- Legacy code remains
- SSE View stays incomplete
- Technical debt continues to accumulate

📊 **Effort:** Low (3-4 tasks)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp[speedups]>=3.13.0` | Core framework | Bumped from >=3.10.0 |

🔗 **Existing Code to Reuse:**
- `navigator/navigator.py:638-684` — Fix _run_unix bug
- `pyproject.toml` — Dependency restructuring

---

## Recommendation

**Option A augmented with targeted Cython benchmarks** is recommended because:

- It addresses all identified issues with clear-cut Cython removal (exceptions, SafeDict, get_logger) while adding data-driven decisions for the two borderline modules: `handlers/base.pyx` (BaseAppHandler) and `utils/types.pyx` (Singleton).
- The benchmarks are scoped to exactly two modules — not the full audit of Option B — keeping effort manageable while providing real evidence for the keep/convert decision.
- Each task is independently deliverable and testable, making it safe for incremental release.
- The URL class investigation and `yarl.URL` migration remain out of scope (future follow-up), avoiding the full weight of Option B.
- Option C leaves too much debt on the table — the Cython cleanup and SSE View are overdue.

**Benchmark scope:**
- `handlers/base.pyx` — Benchmark `BaseAppHandler.__init__()` + `CreateApp()` in Cython vs pure Python equivalent. If the difference is <5% (expected given it's a one-shot startup operation), convert to pure Python.
- `utils/types.pyx` — Benchmark `Singleton.__call__()` Cython vs `datamodel.typedefs.singleton.Singleton`. If equivalent or datamodel is faster, remove the Cython version entirely.
- Results drive the decision: keep Cython only if measured speedup exceeds 10% on the hot path.

---

## Feature Description

### User-Facing Behavior

For **framework users** (application developers):
- No breaking API changes — existing applications continue to work
- Faster `pip install` due to trimmed base dependencies
- Proper IDE support for Cython modules (`.pyi` stubs)
- New `SSEView` class that integrates with navigator's view system (CORS, sessions, JSON encoding)
- SSL support is now tested and reliable
- Smaller dependency footprint: optional features (Google services, proxy support, data visualization) move to extras

For **framework maintainers**:
- Cleaner codebase: exceptions are plain Python, no compilation needed for simple class hierarchies
- Removed dead code: legacy runner, shadowed SafeDict/Singleton
- Fixed bug in Unix socket startup
- Modern aiohttp 3.13+ as baseline

### Internal Behavior

**Cython cleanup flow:**
1. Convert `exceptions/exceptions.pyx` → `exceptions/exceptions.py` preserving exact same class hierarchy and API
2. Remove `exceptions/exceptions.pxd` and compiled `.so`
3. Delete `utils/functions.pyx` and `utils/functions.pxd` — `SafeDict` comes from `datamodel`, `get_logger` becomes a 5-line pure Python function
4. Benchmark `utils/types.pyx` Singleton vs `datamodel.typedefs.singleton.Singleton` — if Cython version has no meaningful advantage, remove and use datamodel's
5. Benchmark `handlers/base.pyx` BaseAppHandler: Cython vs pure Python equivalent — measure `__init__()` + `CreateApp()` cycle. If <10% speedup, convert to pure Python
6. Update `setup.py` to remove deleted extension definitions
7. Add `.pxd`/`.pyi` stubs for any remaining Cython modules (`applications/base.pyx`, `types.pyx`, and `handlers/base.pyx` if it stays Cython)

**AppRunner modernization flow:**
1. Fix `_run_unix()` bug: `path` → `unix_path` at lines 673, 680
2. Remove `_run_legacy()` method entirely
3. Remove `use_legacy_runner` flag handling in `run()`
4. Verify `start_server()` → `_run_tcp()`/`_run_unix()` path works correctly

**SSE View flow:**
1. Create `SSEView` class inheriting from `BaseView` (or `BaseHandler`)
2. SSEView wraps existing `SSEManager` with proper view lifecycle
3. Developers override `async def handle_event()` or similar hook
4. SSEView auto-registers with CORS, handles connection lifecycle

**Dependency cleanup flow:**
1. Move to optional extras: `cartopy`, `matplotlib`, `polyline`, `google-cloud-*` → `[google]` extra
2. Move: `beautifulsoup4`, `proxylists`, `PySocks`, `aiosocks` → `[scraping]` extra
3. Move: `Faker` → `[dev]` or `[testing]` extra (not imported anywhere)
4. Remove: `psycopg2-binary`, `pyarrow` (not directly imported)
5. Bump: `aiohttp[speedups]>=3.13.0`
6. Evaluate: `redis` override-dependency still needed?

### Edge Cases & Error Handling

- **Import compatibility**: After moving deps to extras, any top-level import that previously worked must either continue working (lazy import) or produce a clear error message ("Install navigator-api[google] for Google services support")
- **Cython .so cleanup**: Build artifacts (`.so` files) from deleted Cython modules must be cleaned from installed packages. `setup.py` update handles this for new installs; upgrade path needs documentation.
- **SSL test certificates**: Tests need self-signed certificates generated at test time, not committed to repo. Use `trustme` or `cryptography` for test cert generation.
- **SSEView backward compat**: Existing `SSEMixin` and `SSEEventView` must continue working for users who adopted them. New `SSEView` is an addition, not a replacement.

---

## Capabilities

### New Capabilities
- `sse-view`: Class-based View for SSE that inherits from navigator's BaseView with full CORS/session/JSON integration
- `ssl-testing`: pytest fixtures and tests for SSL/TLS server configuration
- `dependency-extras`: Optional dependency groups for google, scraping, etc.

### Modified Capabilities
- `cython-build`: Reduced set of Cython extensions (remove exceptions, utils/functions, utils/types)
- `app-runner`: Fixed Unix socket support, removed legacy runner
- `exception-system`: Converted from Cython to pure Python (same API)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator/exceptions/` | modifies | Cython → pure Python, same public API |
| `navigator/utils/functions.pyx` | removes | SafeDict/get_logger from datamodel or inline |
| `navigator/utils/types.pyx` | removes | Singleton from datamodel |
| `navigator/utils/__init__.py` | modifies | Already imports from datamodel, remove dead references |
| `navigator/navigator.py` | modifies | Fix _run_unix bug, remove _run_legacy |
| `navigator/services/sse/` | extends | New SSEView class |
| `navigator/views/__init__.py` | extends | Export SSEView |
| `setup.py` | modifies | Remove deleted Cython extensions, add .pyi stubs |
| `pyproject.toml` | modifies | Bump aiohttp, restructure dependencies into extras |
| `navigator/handlers/base.pyx` | extends | Add .pyi stub file |
| `navigator/applications/base.pyx` | extends | Add .pyi stub file |
| `navigator/types.pyx` | extends | Add .pxd/.pyi stub files |
| `tests/` | extends | New SSL tests, SSE view tests |

---

## Code Context

### User-Provided Code
```python
# Source: user-provided (from brainstorm request)
# aiohttp speedups install command
# uv pip install aiohttp[speedups]
```

### Verified Codebase References

#### Classes & Signatures
```python
# From navigator/exceptions/exceptions.pyx:7-73
# cdef class NavException(Exception):
#     def __init__(self, str message='', int state=500, **kwargs)  # line 8
#     def __str__(self)  # line 17
#     def get(self)  # line 22
# Subclasses: InvalidArgument(406), ConfigError(500), ValidationError(410),
#   UserNotFound(404), Unauthorized(401), InvalidAuth(401), FailedAuth(403),
#   AuthExpired(410), ActionError(400)

# From navigator/handlers/base.pyx:20-238
# cdef class BaseAppHandler:
#     def __init__(self, context: dict, app_name: str = None, evt: asyncio.AbstractEventLoop = None)  # line 32
#     def CreateApp(self) -> WebApp  # line 72
#     def setup_cors(self)  # line 123
#     def configure(self)  # line 144
#     def add_routes(self, routes: list)  # line 160
#     async def on_startup(self, app)  # line 221
#     async def on_shutdown(self, app)  # line 227

# From navigator/applications/base.pyx:20-80
# cdef class BaseApplication:
#     def __init__(self, handler=None, title='', contact='', description='', evt=None, **kwargs)  # line 22
#     def get_app(self) -> WebApp  # line 52
#     def setup_app(self) -> WebApp  # line 55
#     def setup(self) -> WebApp  # line 73

# From navigator/types.pyx:26-124
# cdef class URL:
#     cdef str value, scheme, path, host, port, netloc, query, fragment  # lines 27-35
#     cdef dict params  # line 35
#     cdef bool is_absolute  # line 36
#     cpdef URL change_scheme(self, str scheme)  # line 96
#     cpdef URL change_host(self, str host)  # line 109

# From navigator/utils/types.pyx:4-28
# cdef class Singleton(type):
#     cdef dict _instances  # line 11
#     def __call__(cls, *args, **kwargs)  # line 13

# From navigator/utils/functions.pyx:7-26
# def get_logger(str logger_name)  # line 7
# cdef class SafeDict(dict):  # line 17
#     def __missing__(self, str key)  # line 24

# From navigator/services/sse/mixin.py:175-195
# class SSEEventView(SSEMixin):
#     async def get(self) -> web.StreamResponse  # line 184

# From navigator/services/sse/mixin.py:12-172
# class SSEMixin:
#     def sse_manager(self) -> SSEManager  # property, line 49
#     async def create_task(self, task_type, user_id=None, metadata=None) -> str  # line 59
#     async def notify_progress(self, task_id, progress_data) -> int  # line 86
#     async def notify_result(self, task_id, result_data, close_connections=True) -> int  # line 103
#     async def notify_error(self, task_id, error_data, close_connections=True) -> int  # line 124

# From navigator/views/base.py (imported from navigator/views/__init__.py:7)
# class BaseHandler — abstract base class for views
# class BaseView — main view class with JSON, CORS, session support
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from navigator.exceptions import NavException  # navigator/exceptions/__init__.py
from navigator.views import BaseHandler, BaseView  # navigator/views/__init__.py:7
from navigator.services.sse.manager import SSEManager  # navigator/services/sse/manager.py:36
from navigator.services.sse.mixin import SSEMixin, SSEEventView  # navigator/services/sse/mixin.py:12,175
from navigator.utils import SafeDict, Singleton  # navigator/utils/__init__.py (from datamodel)
from navigator.types import WebApp, URL  # navigator/types.pyx:12,26
from datamodel.typedefs.types import SafeDict, AttrDict, NullDefault  # re-exported in navigator/utils/__init__.py
from datamodel.typedefs.singleton import Singleton  # re-exported in navigator/utils/__init__.py
```

#### Key Attributes & Constants
- `NavException.state` → `int` (HTTP status code, navigator/exceptions/exceptions.pyx:9)
- `NavException.stacktrace` → `str` (navigator/exceptions/exceptions.pyx:13)
- `BaseAppHandler.cors` → `aiohttp_cors.CorsConfig` (navigator/handlers/base.pyx:87)
- `BaseAppHandler.app` → `WebApp` (navigator/handlers/base.pyx:42)
- `SSEManager._connections` → `Dict[str, List[SSEConnection]]` (navigator/services/sse/manager.py:57)
- `FORCED_CIPHERS` → `str` (navigator/navigator.py, SSL cipher string)

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.views.SSEView`~~ — does not exist yet (SSEEventView is in services/sse/mixin.py, not in views)
- ~~`navigator.utils.functions.SafeDict` (runtime import)~~ — the .pyx defines it but `navigator/utils/__init__.py` imports from `datamodel` instead, shadowing the Cython version
- ~~`navigator.utils.types.Singleton` (runtime import)~~ — same: shadowed by datamodel import in `utils/__init__.py`
- ~~`aiohttp` built-in CORS middleware~~ — does not exist in aiohttp core; CORS is handled by `aiohttp-cors` (aiolibs)
- ~~`navigator/types.pxd`~~ — does not exist, needs to be created
- ~~`navigator/types.pyi`~~ — does not exist, needs to be created
- ~~`navigator/handlers/base.pyi`~~ — does not exist, needs to be created
- ~~`Faker` usage in navigator~~ — Faker is not imported anywhere in the codebase
- ~~`psycopg2` direct usage in navigator~~ — not imported anywhere (transitive via asyncdb)
- ~~`pyarrow` direct usage in navigator~~ — not imported anywhere

---

## Parallelism Assessment

- **Internal parallelism**: High. Tasks decompose into several independent streams:
  - Stream 0: Cython benchmarks (handlers/base.pyx, Singleton) — must run FIRST, results inform Stream 1
  - Stream 1: Cython cleanup (exceptions → pure Python, remove dead utils, benchmark-driven decisions on handlers/base and Singleton, add .pyi stubs)
  - Stream 2: AppRunner fixes (unix bug fix, remove legacy runner)
  - Stream 3: Dependency restructuring (pyproject.toml extras, bump aiohttp)
  - Stream 4: SSE View class creation
  - Stream 5: SSL test suite
  Stream 0 runs first. Then Streams 1-3 can run in parallel (touch different files). Stream 4 depends on knowing the final BaseView API (already stable). Stream 5 is fully independent and can run alongside anything.

- **Cross-feature independence**: No conflicts with in-flight specs. navigator-api is not currently under active feature development.

- **Recommended isolation**: `mixed` — Streams 1, 4, and 5 can use individual worktrees. Streams 2 and 3 both touch `navigator/navigator.py` and `pyproject.toml` respectively and should be sequential.

- **Rationale**: The feature naturally decomposes into independent concerns (Cython cleanup vs SSE vs SSL tests vs dependencies). Only the AppRunner/dependency tasks share files. Parallel worktrees for the independent streams will speed delivery.

---

## Open Questions

- [ ] Should `navigator/types.pyx` URL class remain Cython long-term, or plan a `yarl.URL` migration as a follow-up feature? — *Owner: Jesus Lara*
- [ ] Is `sockjs>=0.11.0` still needed? Only imported conditionally in `navigator.py:19`. — *Owner: Jesus Lara*
- [ ] Should `aiohttp-sse` be vendored or forked given no new releases in 2 years (last release 2024)? Or is it stable enough as-is? — *Owner: Jesus Lara*
- [ ] What is the `redis==5.2.1` override-dependency in `[tool.uv]` for? Is this still needed with the latest navigator-session? — *Owner: Jesus Lara*
- [ ] Should the new `SSEView` replace `SSEEventView` or coexist alongside it? — *Owner: Jesus Lara*
- [ ] `navigator/actions/google/maps.py` does top-level imports of `cartopy` and `matplotlib` — these need to become lazy imports when moved to extras. Confirm no startup-time side effects. — *Owner: Jesus Lara*
