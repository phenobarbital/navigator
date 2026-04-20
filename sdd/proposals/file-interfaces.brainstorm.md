# Brainstorm: File Manager Interfaces Modernization

**Date**: 2026-04-20
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

Navigator's file manager utilities (`navigator/utils/file/`) suffer from several architectural issues:

1. **No shared interface**: `GCSFileManager`, `S3FileManager`, and `TempFileManager` are three independent classes with similar but inconsistent APIs — no ABC, no shared protocol.
2. **Mixed sync/async**: GCS and TempFile managers are synchronous (blocking I/O), only S3 is async. This violates Navigator's async-first principle.
3. **Tight web coupling**: Each manager embeds aiohttp route registration (`setup(app)`) and HTTP streaming (`handle_file(request)`) directly in the file manager class, mixing storage concerns with HTTP concerns.
4. **No local filesystem manager**: There's no `LocalFileManager` for local disk operations.
5. **No unified metadata**: Methods return raw strings (blob names, keys) instead of a structured metadata object.
6. **No multipart upload support**: Large files are uploaded as a single blob, no chunking or concurrency.
7. **No sandboxing**: Beyond basic path traversal checks in TempFileManager, there's no systematic path safety.

AI-Parrot (`parrot/interfaces/file/`) has already solved these problems with a clean rewrite. Since Navigator is a dependency of AI-Parrot, the code should live in Navigator and be imported by AI-Parrot.

**Who is affected**: Developers using `navigator.utils.file` and all AI-Parrot code that imports file managers.

## Constraints & Requirements

- **Backward compatibility**: Existing `setup(app)` / `handle_file(request)` web integration must continue to work. The web-serving layer moves to a separate module but preserves the same signatures.
- **Async-first**: All file manager methods must be `async def`. Blocking SDK calls (GCS, local FS) wrapped in `asyncio.to_thread()`.
- **Configuration**: Managers accept credentials as constructor parameters. `AWS_CREDENTIALS` from `navigator.conf` is the default, not a hard dependency.
- **FileMetadata**: Adopt the `FileMetadata` dataclass as the standard return type across all managers.
- **Sandboxing**: Default-on for all managers (path traversal protection, optional symlink blocking).
- **Multipart uploads**: Must-have for both S3 and GCS.
- **No new standalone packages**: Code lives in Navigator, AI-Parrot imports from Navigator.
- **Lazy loading**: Cloud provider dependencies (aioboto3, google-cloud-storage) must not be imported at module load time.

---

## Options Explored

### Option A: Incremental Refactor of Navigator's Existing Code

Add the `FileManagerInterface` ABC and `FileMetadata` to Navigator's existing file utilities. Refactor each manager in-place to implement the interface, converting sync methods to async. Extract web-serving into a separate mixin or module.

Pros:
- Minimal disruption — changes are incremental.
- No risk of missing Navigator-specific features (folder operations, signed URLs, Range requests).
- Existing tests (if any) can be updated incrementally.

Cons:
- The existing code has no consistent structure — refactoring in-place means fighting the current design.
- GCS manager is fully synchronous with deeply embedded blocking calls — wrapping every method in `asyncio.to_thread()` is tedious and error-prone.
- Multipart upload, sandboxing, and factory pattern would need to be built from scratch.
- Risk of "half-old, half-new" code that's harder to maintain.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async S3 operations | Already used |
| `google-cloud-storage` | GCS operations | Already used, sync |
| `aiohttp` | Web integration | Already used |

**Existing Code to Reuse:**
- `navigator/utils/file/gcs.py` — folder operations (create/remove/rename), signed URL generation, Range request handling
- `navigator/utils/file/s3.py` — async paginated listing, presigned URL generation
- `navigator/utils/file/tmp.py` — path traversal sanitization pattern

---

### Option B: Port AI-Parrot's File Interfaces into Navigator (Recommended)

Copy AI-Parrot's `parrot/interfaces/file/` into `navigator/utils/file/`, adapting it to Navigator's config system and adding a compatibility web-serving layer. This brings the ABC, FileMetadata, LocalFileManager, TempFileManager, S3 multipart, GCS resumable uploads, sandboxing, and factory pattern — all already tested and working.

Then add:
1. A `web.py` module with `FileServingExtension` that delegates to any `FileManagerInterface` implementation for aiohttp route registration and streaming.
2. Navigator-specific features not in AI-Parrot (GCS folder operations, Range request support, `find_files()`).
3. Backward-compatible `setup(app)` and `handle_file(request)` methods on each manager that delegate to the web layer.

Pros:
- Starts from a clean, proven architecture with ABC + FileMetadata + async-first + sandboxing.
- Multipart uploads (S3) and resumable uploads (GCS) come for free.
- Factory pattern and lazy loading already implemented.
- LocalFileManager included — fills a real gap in Navigator.
- AI-Parrot can immediately switch to `from navigator.utils.file import ...`.
- Significantly less new code to write — most is adaptation.

Cons:
- Requires porting Navigator-specific features (folder ops, Range requests, find_files) that AI-Parrot doesn't have.
- The web-serving layer is new code that needs to be built.
- Two codebases briefly coexist during transition (old and new).
- `navigator.conf` integration replaces `parrot.conf` references.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async S3 with multipart | Already a Navigator dependency |
| `google-cloud-storage` | GCS operations | Already a Navigator dependency |
| `aiohttp` | Web serving layer | Already a Navigator dependency |
| `mimetypes` | Content type detection | stdlib |
| `asyncio` | `to_thread()` for blocking calls | stdlib |

**Existing Code to Reuse:**
- `parrot/interfaces/file/abstract.py` — `FileManagerInterface` ABC, `FileMetadata` dataclass
- `parrot/interfaces/file/local.py` — `LocalFileManager` with sandboxing
- `parrot/interfaces/file/tmp.py` — `TempFileManager` with auto-cleanup and context manager
- `parrot/interfaces/file/s3.py` — `S3FileManager` with multipart uploads, concurrent chunking
- `parrot/interfaces/file/gcs.py` — `GCSFileManager` with resumable uploads, credential modes
- `parrot/interfaces/file/__init__.py` — Lazy loading pattern
- `navigator/utils/file/gcs.py` — `setup()`, `handle_file()`, Range request handling, folder operations, `find_files()`
- `navigator/utils/file/s3.py` — `setup()`, `handle_file()`, `find_files()`
- `navigator/utils/file/tmp.py` — `setup()`, `handle_file()`

---

### Option C: Thin Adapter Layer over AI-Parrot's Code

Keep AI-Parrot's file interfaces in AI-Parrot. In Navigator, create thin adapter classes that wrap AI-Parrot's managers, adding Navigator-specific features (web integration, `navigator.conf` credentials). Navigator would depend on AI-Parrot for file management.

Pros:
- No code duplication — single source of truth in AI-Parrot.
- Navigator's file managers become thin wrappers.
- Minimal changes to either codebase.

Cons:
- **Inverts the dependency**: Navigator is a lower-level framework than AI-Parrot. Having Navigator depend on AI-Parrot for file management creates a circular dependency problem.
- AI-Parrot already depends on Navigator — this creates a bidirectional dependency.
- Changes to AI-Parrot's file interfaces would break Navigator.
- Testing becomes more complex across package boundaries.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot` | File interface implementations | Would become a Navigator dependency |

**Existing Code to Reuse:**
- All of `parrot/interfaces/file/` — used as-is via import
- `navigator/utils/file/*.py` — web integration methods extracted as adapters

---

### Option D: Shared File Interfaces Package (Out of Scope)

Extract file interfaces into a standalone `navigator-file` or `file-interfaces` package that both Navigator and AI-Parrot depend on.

Pros:
- Clean separation of concerns.
- Both projects import from a neutral package.
- Independent versioning and testing.

Cons:
- **Explicitly out of scope** per user requirements.
- Adds operational complexity (another package to publish, version, maintain).
- Overkill for an internal shared component.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| N/A | Would be a new package | Out of scope |

**Existing Code to Reuse:**
- Same as Option B

---

## Recommendation

**Option B** is recommended because:

1. **Proven foundation**: AI-Parrot's file interfaces are already working, tested, and well-architected. Porting them saves building the ABC, FileMetadata, sandboxing, multipart uploads, and factory pattern from scratch.
2. **Correct dependency direction**: Navigator is the lower-level framework. File management belongs in Navigator, not in AI-Parrot. Option B respects this hierarchy.
3. **Medium effort**: Most of the core implementation already exists. The new work is (a) adapting config imports, (b) adding Navigator-specific features (folder ops, Range requests, find_files), and (c) building the web-serving layer.
4. **Option A is high-effort for the same result** — we'd end up with the same architecture but built from scratch instead of ported.
5. **Option C creates a circular dependency** — Navigator cannot depend on AI-Parrot.

The main tradeoff is a short period where old and new code coexist, but the migration path is clear: port, adapt, add compatibility shims, switch callers, remove old code.

---

## Feature Description

### User-Facing Behavior

Developers using `navigator.utils.file` get:

- **Same imports, better types**: `from navigator.utils.file import S3FileManager, GCSFileManager, TempFileManager, LocalFileManager, FileMetadata`
- **Uniform async API**: All managers implement `FileManagerInterface` with methods like `list_files()`, `upload_file()`, `download_file()`, `copy_file()`, `delete_file()`, `exists()`, `get_file_metadata()`.
- **Rich metadata returns**: Methods return `FileMetadata` objects instead of raw strings.
- **New LocalFileManager**: Local disk operations with sandboxing.
- **Web integration preserved**: `manager.setup(app)` and `manager.handle_file(request)` continue to work, delegating to a new `FileServingExtension`.
- **Factory creation**: `FileManagerFactory.create("s3", bucket_name="my-bucket")` for runtime selection.

### Internal Behavior

```
navigator/utils/file/
  __init__.py          # Exports + lazy loading (cloud managers)
  abstract.py          # FileManagerInterface ABC + FileMetadata dataclass
  local.py             # LocalFileManager (async via to_thread, sandboxed)
  tmp.py               # TempFileManager (auto-cleanup, context manager)
  s3.py                # S3FileManager (aioboto3, multipart uploads)
  gcs.py               # GCSFileManager (google-cloud-storage, resumable uploads)
  web.py               # FileServingExtension (aiohttp routes, streaming, Range requests)
  factory.py           # FileManagerFactory (create by type string)
```

**Flow for a file upload**:
1. Caller creates a manager (directly or via factory).
2. Calls `await manager.upload_file(source, destination)`.
3. Manager checks sandboxing constraints (if applicable).
4. For large files (S3: >100MB, GCS: >5MB), multipart/resumable upload kicks in automatically.
5. Returns `FileMetadata` with name, path, size, content_type, modified_at, url.

**Flow for web serving**:
1. Caller calls `manager.setup(app, route='/data')` — this delegates to `FileServingExtension`.
2. Extension registers GET route `route + "/{filepath:.*}"`.
3. On request, extension calls `manager.download_file()` or streams directly from storage.
4. Supports Range requests (HTTP 206) for GCS and S3.

**Configuration flow**:
1. S3FileManager accepts `aws_key`, `aws_secret`, `region_name` as constructor params.
2. If not provided, falls back to `AWS_CREDENTIALS.get(aws_id)` from `navigator.conf`.
3. GCS accepts `json_credentials` dict, `credentials` file path, or falls back to `google.auth.default()`.

### Edge Cases & Error Handling

- **Missing credentials**: `ValueError` raised at construction time with clear message.
- **File not found**: `download_file()` and `get_file_metadata()` raise `FileNotFoundError`.
- **Path traversal**: Sandboxing rejects paths that escape the base directory. `ValueError` raised.
- **Multipart upload failure (S3)**: Incomplete uploads are aborted (cleanup of S3 parts).
- **Resumable upload failure (GCS)**: Retries with exponential backoff, then raises.
- **Large file listing**: S3 uses paginated listing to avoid memory issues. GCS iterates blobs lazily.
- **Web handler 404**: Returns `web.Response(status=404)` for missing files.
- **Web handler Range errors**: Returns `web.HTTPBadRequest` for malformed Range headers.
- **Temp cleanup**: TempFileManager cleans up on `__del__`, `atexit`, or explicit `cleanup()`. Errors during cleanup are suppressed.
- **Lazy import failure**: If `aioboto3` or `google-cloud-storage` not installed, `ImportError` raised only when the specific manager is accessed.

---

## Capabilities

### New Capabilities
- `file-manager-interface`: Abstract base class (FileManagerInterface) and FileMetadata dataclass providing a unified async contract for all file storage backends.
- `local-file-manager`: LocalFileManager for local disk operations with sandboxing and async I/O.
- `file-serving-web-layer`: FileServingExtension for aiohttp route registration and HTTP file streaming, decoupled from storage managers.
- `file-manager-factory`: FileManagerFactory for runtime creation of file managers by type string.
- `multipart-upload-s3`: Configurable multipart upload support for S3 (threshold, chunk size, concurrency).
- `resumable-upload-gcs`: Resumable upload support for GCS with configurable threshold.
- `file-manager-sandboxing`: Default-on path sandboxing across all managers (path traversal protection, symlink control).

### Modified Capabilities
- `gcs-file-manager`: Rewritten to implement FileManagerInterface, async-first, with resumable uploads. Preserves folder operations and signed URL generation. Web serving delegates to file-serving-web-layer.
- `s3-file-manager`: Rewritten to implement FileManagerInterface with multipart uploads. Preserves presigned URL and paginated listing. Web serving delegates to file-serving-web-layer.
- `temp-file-manager`: Rewritten to implement FileManagerInterface with auto-cleanup, context manager support, and sandboxing. Web serving delegates to file-serving-web-layer.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator/utils/file/__init__.py` | replaces | New exports: FileManagerInterface, FileMetadata, LocalFileManager, factory |
| `navigator/utils/file/gcs.py` | replaces | Rewritten with ABC, async, resumable uploads. Folder ops preserved |
| `navigator/utils/file/s3.py` | replaces | Rewritten with ABC, multipart uploads. Config adapter for navigator.conf |
| `navigator/utils/file/tmp.py` | replaces | Rewritten with ABC, context manager, auto-cleanup |
| `navigator/utils/file/abstract.py` | new | FileManagerInterface ABC + FileMetadata dataclass |
| `navigator/utils/file/local.py` | new | LocalFileManager implementation |
| `navigator/utils/file/web.py` | new | FileServingExtension for aiohttp integration |
| `navigator/utils/file/factory.py` | new | FileManagerFactory |
| `navigator/conf.py` | depends on | AWS_CREDENTIALS used as default for S3 manager |
| `navigator/extensions.py` | extends | FileServingExtension follows BaseExtension pattern |
| AI-Parrot `parrot/interfaces/file/` | depends on | Will switch to importing from `navigator.utils.file` |

---

## Code Context

### User-Provided Code
No code snippets were provided during brainstorming.

### Verified Codebase References

#### AI-Parrot — Source implementations to port

```python
# From /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src/parrot/interfaces/file/abstract.py:8-16
@dataclass
class FileMetadata:
    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]

# From /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src/parrot/interfaces/file/abstract.py:18-76
class FileManagerInterface(ABC):
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]: ...
    async def get_file_url(self, path: str, expiry: int = 3600) -> str: ...
    async def upload_file(self, source: BinaryIO | Path, destination: str) -> FileMetadata: ...
    async def download_file(self, source: str, destination: Path | BinaryIO) -> Path: ...
    async def copy_file(self, source: str, destination: str) -> FileMetadata: ...
    async def delete_file(self, path: str) -> bool: ...
    async def exists(self, path: str) -> bool: ...
    async def get_file_metadata(self, path: str) -> FileMetadata: ...
    async def create_file(self, path: str, content: bytes) -> bool: ...
    async def create_from_text(self, path: str, text: str, encoding: str = "utf-8") -> bool:  # concrete
    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool:  # concrete
```

```python
# From /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src/parrot/interfaces/file/__init__.py:23-35
# Lazy loading pattern
_LAZY_MANAGERS = {
    "S3FileManager": ".s3",
    "GCSFileManager": ".gcs",
}

def __getattr__(name: str):
    if name in _LAZY_MANAGERS:
        mod = importlib.import_module(_LAZY_MANAGERS[name], __name__)
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

#### Navigator — Existing code to preserve or adapt

```python
# From navigator/utils/file/gcs.py:20-79
class GCSFileManager:
    def __init__(self, bucket_name: str, route: str = '/data', **kwargs): ...
    # key methods (all sync):
    def list_all_files(self, prefix=None) -> list: ...          # line 81
    def list_files(self, prefix=None) -> List[str]: ...         # line 94
    def upload_file(self, source_file_path, destination_blob_name) -> str: ...  # line 107
    def upload_file_from_bytes(self, file_obj, destination_blob_name, content_type='application/zip') -> str: ...  # line 128
    def upload_file_from_string(self, data, destination_blob_name) -> str: ...  # line 150
    def delete_file(self, blob_name): ...                       # line 165
    def find_files(self, keywords=None, extension=None, prefix=None) -> list: ...  # line 375
    def create_folder(self, folder_name): ...                   # line 405
    def remove_folder(self, folder_name): ...                   # line 418
    def rename_folder(self, old_folder_name, new_folder_name): ...  # line 431
    def rename_file(self, old_file_name, new_file_name): ...    # line 449
    # web integration:
    def setup(self, app, route='data', base_url=None): ...      # line 300
    async def handle_file(self, request): ...                   # line 207
    def get_file_url(self, blob_name, base_url=None, use_signed_url=False, expiration=3600) -> str: ...  # line 330
    def parse_range_header(self, range_header, file_size) -> tuple: ...  # line 276
```

```python
# From navigator/utils/file/s3.py:20-64
class S3FileManager:
    manager_name: str = 's3file'
    def __init__(self, bucket_name=None, route='/data', aws_id='default', **kwargs): ...
    # key methods (all async):
    async def list_files(self, prefix=None) -> AsyncGenerator: ...  # line 66
    async def upload_file(self, source_file_path, destination_key) -> str: ...  # line 85
    async def upload_file_from_bytes(self, file_obj, destination_key, content_type='application/octet-stream') -> str: ...  # line 100
    async def delete_file(self, key): ...                       # line 126
    async def generate_presigned_url(self, key, expiration=3600) -> str: ...  # line 136
    async def find_files(self, keywords=None, extension=None, prefix=None) -> list: ...  # line 155
    # web integration:
    def setup(self, app, route='/data', base_url=None): ...     # line 235
    async def handle_file(self, request): ...                   # line 187
```

```python
# From navigator/utils/file/tmp.py:16-128
class TempFileManager:
    def __init__(self): ...
    @staticmethod
    def create_temp_file(suffix='', prefix='tmp', dir=None) -> str: ...  # line 28
    @staticmethod
    def remove_temp_file(file_path): ...                        # line 37
    async def handle_file(self, request): ...                   # line 46
    def setup(self, app, route='data', base_url=None): ...      # line 70
    def get_file_url(self, temp_file_path, base_url=None) -> str: ...  # line 100
```

```python
# From navigator/extensions.py:23-67
class BaseExtension(ABC):
    name: str = None
    app: WebApp = None
    on_startup: Optional[Callable] = None
    on_shutdown: Optional[Callable] = None
    on_cleanup: Optional[Callable] = None
    on_context: Optional[Callable] = None
    middleware: Optional[Callable] = None
    def __init__(self, *args, app_name: str = None, **kwargs): ...
    def setup(self, app: WebApp) -> WebApp: ...  # line 59
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from navigator.utils.file import TempFileManager, GCSFileManager, S3FileManager  # navigator/utils/file/__init__.py
from navigator.conf import AWS_CREDENTIALS  # navigator/utils/file/s3.py:14
from navigator.types import WebApp  # navigator/types.pyx (WebApp = web.Application)
from navigator.applications.base import BaseApplication  # used by all managers
from navigator.extensions import BaseExtension  # navigator/extensions.py:23
from navconfig.logging import logging  # used by GCS and S3 managers
```

#### Key Attributes & Constants
- `S3FileManager.manager_name` -> `str` = `'s3file'` (navigator/utils/file/s3.py:26)
- `GCSFileManager.bucket` -> `google.cloud.storage.Bucket` (navigator/utils/file/gcs.py:75)
- `GCSFileManager.client` -> `google.cloud.storage.Client` (navigator/utils/file/gcs.py:72-74)
- AI-Parrot `S3FileManager.MULTIPART_THRESHOLD` -> `int` = `104857600` (100MB) (parrot s3.py:19)
- AI-Parrot `S3FileManager.MULTIPART_CHUNKSIZE` -> `int` = `10485760` (10MB) (parrot s3.py:20)
- AI-Parrot `S3FileManager.MAX_CONCURRENCY` -> `int` = `10` (parrot s3.py:21)
- AI-Parrot `GCSFileManager.RESUMABLE_THRESHOLD` -> `int` = `5242880` (5MB) (parrot gcs.py:20)
- AI-Parrot `GCSFileManager.CHUNK_SIZE` -> `int` = `262144` (256KB) (parrot gcs.py:21)

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.utils.file.abstract`~~ — does not exist yet (to be created)
- ~~`navigator.utils.file.local`~~ — does not exist yet (to be created)
- ~~`navigator.utils.file.web`~~ — does not exist yet (to be created)
- ~~`navigator.utils.file.factory`~~ — does not exist yet (to be created)
- ~~`navigator.utils.file.FileManagerInterface`~~ — does not exist in Navigator
- ~~`navigator.utils.file.FileMetadata`~~ — does not exist in Navigator
- ~~`navigator.utils.file.LocalFileManager`~~ — does not exist in Navigator
- ~~`GCSFileManager.download_file()`~~ — does not exist in current Navigator GCS manager
- ~~`GCSFileManager.copy_file()`~~ — does not exist in current Navigator GCS manager
- ~~`GCSFileManager.exists()`~~ — does not exist in current Navigator GCS manager
- ~~`S3FileManager.download_file()`~~ — does not exist in current Navigator S3 manager
- ~~`S3FileManager.copy_file()`~~ — does not exist in current Navigator S3 manager
- ~~`S3FileManager.exists()`~~ — does not exist in current Navigator S3 manager
- ~~`TempFileManager.upload_file()`~~ — does not exist in current Navigator TempFileManager
- ~~`TempFileManager.list_files()`~~ — does not exist in current Navigator TempFileManager

---

## Parallelism Assessment

- **Internal parallelism**: Yes — this feature decomposes well into independent tasks. The ABC/FileMetadata can be done first, then LocalFileManager, S3FileManager, GCSFileManager, TempFileManager, and the web layer can all be worked on in parallel since they share only the interface contract.
- **Cross-feature independence**: Low conflict risk. The only shared files are `navigator/utils/file/__init__.py` (final wiring) and potentially `navigator/conf.py` (no changes needed). No in-flight specs touch `navigator/utils/file/`.
- **Recommended isolation**: `per-spec` — all tasks in one worktree. While managers are independent, they share the same directory and the `__init__.py` wiring needs coordinated updates. Sequential execution in one worktree avoids merge conflicts.
- **Rationale**: The ABC must land first (all managers depend on it). The web layer depends on at least one manager being done. A single worktree with sequential tasks keeps things simple and avoids `__init__.py` conflicts.

---

## Open Questions

- [x] Should `find_files()` be added to `FileManagerInterface` or remain a manager-specific method? It exists in Navigator's GCS and S3 but not in AI-Parrot's interface. — *Owner: Jesus*: added to FileManagerInterface then added also in Local and Temp file managers.
- [x]] Should GCS folder operations (`create_folder`, `remove_folder`, `rename_folder`, `rename_file`) be part of the interface or GCS-specific extensions? — *Owner: Jesus*: be part of the interface
- [x] What is the exact structure of `AWS_CREDENTIALS` in `navigator.conf`? It's imported in `s3.py` but not defined in `conf.py` — likely comes from `navconfig`. Need to verify the dict structure. — *Owner: Jesus*: is a dictionary with keys: ```AWS_CREDENTIALS = {
    "default": {
        "use_credentials": config.get("aws_credentials", fallback=False),
        "aws_key": aws_key,
        "aws_secret": aws_secret,
        "region_name": aws_region,
        "bucket_name": aws_bucket,
    },
    "monitoring": {
        "use_credentials": config.get("aws_monitor_credentials", fallback=True),
        "aws_key": AWS_ACCESS_KEY,
        "aws_secret": AWS_SECRET_KEY,
        "region_name": AWS_REGION_NAME,
    },```
- [x] Should `FileServingExtension` extend `BaseExtension`, or be a standalone utility class? BaseExtension provides `setup(app)` + signal registration, which fits well. — *Owner: Jesus*: extend BaseExtension.
- [x] When AI-Parrot switches to `from navigator.utils.file import ...`, should we keep `parrot/interfaces/file/` as a re-export shim or remove it entirely? — *Owner: Jesus*: should be keep as a re-export shim.
