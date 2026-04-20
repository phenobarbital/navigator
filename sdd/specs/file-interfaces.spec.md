# Feature Specification: File Manager Interfaces Modernization

**Feature ID**: FEAT-002
**Date**: 2026-04-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Navigator's file manager utilities (`navigator/utils/file/`) have no shared interface, mixed sync/async behavior, tight web-framework coupling, no local filesystem manager, no unified metadata, no multipart upload support, and no systematic sandboxing. AI-Parrot (`parrot/interfaces/file/`) has already solved these problems with a clean rewrite built on an ABC, `FileMetadata` dataclass, async-first design, sandboxing, multipart/resumable uploads, and a factory pattern. Since Navigator is a dependency of AI-Parrot (not the reverse), the canonical file manager code should live in Navigator so AI-Parrot can import it.

### Goals
- Provide a unified `FileManagerInterface` ABC that all file managers implement.
- Return `FileMetadata` objects instead of raw strings from all operations.
- Make all file manager methods async (blocking SDKs wrapped in `asyncio.to_thread()`).
- Add `LocalFileManager` for local disk operations.
- Add multipart uploads (S3, 100MB threshold) and resumable uploads (GCS, 5MB threshold).
- Add default-on sandboxing (path traversal protection) across all managers.
- Decouple web-serving (aiohttp routes, streaming) into a separate `FileServingExtension`.
- Preserve backward compatibility for `setup(app)` / `handle_file(request)`.
- Add `FileManagerFactory` for runtime creation by type string.
- Enable AI-Parrot to `from navigator.utils.file import FileManagerInterface, ...`.

### Non-Goals (explicitly out of scope)
- Creating a standalone shared package (code lives in Navigator).
- Rewriting Navigator's `BaseExtension` or handler infrastructure.
- Adding new cloud storage backends (Azure Blob, MinIO) in this iteration.
- Modifying AI-Parrot's code to import from Navigator (that's a separate follow-up task).

---

## 2. Architectural Design

### Overview

Port AI-Parrot's `parrot/interfaces/file/` into `navigator/utils/file/`, adapting imports to Navigator's config system (`navigator.conf`) and logging (`navconfig.logging`). Add Navigator-specific features not present in AI-Parrot: GCS folder operations, Range request support, `find_files()`, and a web-serving layer (`FileServingExtension`) that replaces the current inline `setup()`/`handle_file()` pattern.

Each existing manager (GCS, S3, Temp) is rewritten to implement `FileManagerInterface`. A new `LocalFileManager` is added. Backward-compatible `setup(app)` and `handle_file(request)` methods are retained on each manager but delegate to `FileServingExtension`.

### Component Diagram
```
                     FileManagerInterface (ABC)
                     FileMetadata (dataclass)
                            │
            ┌───────────────┼───────────────────────┐
            │               │                       │
   ┌────────┴───────┐  ┌───┴────────┐  ┌──────────┴────────┐
   │ LocalFileManager│  │TempFileMgr │  │  Cloud Managers    │
   │  (sandboxed,   │  │ (auto-clean │  │  (lazy-loaded)     │
   │   to_thread)   │  │  ctx mgr)  │  │                    │
   └────────────────┘  └────────────┘  │  ┌──────────────┐  │
                                       │  │S3FileManager │  │
                                       │  │(multipart)   │  │
                                       │  └──────────────┘  │
                                       │  ┌──────────────┐  │
                                       │  │GCSFileManager│  │
                                       │  │(resumable)   │  │
                                       │  └──────────────┘  │
                                       └────────────────────┘
                            │
                    FileManagerFactory
                            │
                   FileServingExtension
                   (aiohttp routes, Range)
                            │
                   ┌────────┴────────┐
                   │ setup(app)      │
                   │ handle_file(req)│
                   └─────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.conf.AWS_CREDENTIALS` | uses (default) | S3 manager reads credentials; constructor params override |
| `navigator.extensions.BaseExtension` | extends | FileServingExtension follows this pattern for `setup(app)` |
| `navigator.types.WebApp` | uses | Type alias for `aiohttp.web.Application` |
| `navigator.applications.base.BaseApplication` | uses | `setup()` unwraps via `get_app()` |
| `navconfig.logging.logging` | uses | Logger for all managers |
| AI-Parrot `parrot/interfaces/file/` | replaces (upstream) | AI-Parrot will import from Navigator instead |

### Data Models
```python
@dataclass
class FileMetadata:
    """Unified metadata returned by all file operations."""
    name: str                           # Filename only
    path: str                           # Relative or full path / key
    size: int                           # File size in bytes
    content_type: Optional[str]         # MIME type
    modified_at: Optional[datetime]     # Last modification timestamp
    url: Optional[str]                  # Public/signed URL if available
```

### New Public Interfaces
```python
class FileManagerInterface(ABC):
    """Base contract for all file managers."""
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]: ...
    async def get_file_url(self, path: str, expiry: int = 3600) -> str: ...
    async def upload_file(self, source: BinaryIO | Path, destination: str) -> FileMetadata: ...
    async def download_file(self, source: str, destination: Path | BinaryIO) -> Path: ...
    async def copy_file(self, source: str, destination: str) -> FileMetadata: ...
    async def delete_file(self, path: str) -> bool: ...
    async def exists(self, path: str) -> bool: ...
    async def get_file_metadata(self, path: str) -> FileMetadata: ...
    async def create_file(self, path: str, content: bytes) -> bool: ...
    # Concrete helpers:
    async def create_from_text(self, path: str, text: str, encoding: str = "utf-8") -> bool: ...
    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool: ...
    # Navigator-specific additions:
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]: ...

class FileManagerFactory:
    """Runtime creation of file managers by type string."""
    @staticmethod
    def create(manager_type: str, **kwargs) -> FileManagerInterface: ...

class FileServingExtension(BaseExtension):
    """Decoupled aiohttp web-serving for any FileManagerInterface."""
    name: str = "fileserving"
    def __init__(self, manager: FileManagerInterface, route: str = "/data", **kwargs): ...
    def setup(self, app: WebApp) -> WebApp: ...
    async def handle_file(self, request: web.Request) -> web.StreamResponse: ...
```

---

## 3. Module Breakdown

### Module 1: Abstract Interface
- **Path**: `navigator/utils/file/abstract.py`
- **Responsibility**: `FileManagerInterface` ABC and `FileMetadata` dataclass. Defines the contract all managers implement. Includes concrete helper methods `create_from_text()` and `create_from_bytes()`.
- **Depends on**: stdlib only (`abc`, `dataclasses`, `typing`, `pathlib`, `io`, `datetime`)

### Module 2: Local File Manager
- **Path**: `navigator/utils/file/local.py`
- **Responsibility**: `LocalFileManager` — local disk operations with sandboxing (path traversal protection, symlink control). All I/O via `asyncio.to_thread()`. Methods: all from interface plus `_resolve_path()` for sandbox enforcement.
- **Depends on**: Module 1 (abstract)

### Module 3: Temp File Manager
- **Path**: `navigator/utils/file/tmp.py`
- **Responsibility**: `TempFileManager` — temporary file storage with auto-cleanup (`atexit`, `__del__`, context manager `async with`). Sandboxed to temp directory. Supports move semantics for `download_file()`.
- **Depends on**: Module 1 (abstract)

### Module 4: S3 File Manager
- **Path**: `navigator/utils/file/s3.py`
- **Responsibility**: `S3FileManager` — AWS S3 operations via `aioboto3`. Configurable multipart uploads (100MB threshold, 10MB chunks, 10 concurrent). Paginated listing. Presigned URLs. Credentials from constructor params with `navigator.conf.AWS_CREDENTIALS` as default. Includes `find_files()`.
- **Depends on**: Module 1 (abstract), `aioboto3`, `navigator.conf`

### Module 5: GCS File Manager
- **Path**: `navigator/utils/file/gcs.py`
- **Responsibility**: `GCSFileManager` — Google Cloud Storage operations. Resumable uploads (5MB threshold). Three credential modes (dict, file, default). Folder operations (`create_folder`, `remove_folder`, `rename_folder`, `rename_file`). Signed URLs. Blocking SDK wrapped in `asyncio.to_thread()`. Includes `find_files()`.
- **Depends on**: Module 1 (abstract), `google-cloud-storage`, `google-auth`

### Module 6: Web Serving Layer
- **Path**: `navigator/utils/file/web.py`
- **Responsibility**: `FileServingExtension` — aiohttp route registration and HTTP file streaming decoupled from storage managers. Supports Range requests (HTTP 206). Registers GET route `{route}/{filepath:.*}`. Follows `BaseExtension` pattern. Streams files from any `FileManagerInterface` implementation.
- **Depends on**: Module 1 (abstract), `navigator.extensions.BaseExtension`, `aiohttp`

### Module 7: Factory
- **Path**: `navigator/utils/file/factory.py`
- **Responsibility**: `FileManagerFactory` — create file managers by type string (`"local"`, `"temp"`, `"s3"`, `"gcs"`). Lazy imports for cloud managers.
- **Depends on**: Module 1 (abstract), Modules 2-5 (lazy)

### Module 8: Package Init & Backward Compatibility
- **Path**: `navigator/utils/file/__init__.py`
- **Responsibility**: Package exports with lazy loading for cloud managers. Exports: `FileManagerInterface`, `FileMetadata`, `LocalFileManager`, `TempFileManager`, `S3FileManager`, `GCSFileManager`, `FileServingExtension`, `FileManagerFactory`. Backward-compatible `setup()` and `handle_file()` convenience wrappers on each manager class.
- **Depends on**: All modules

### Module 9: Tests
- **Path**: `tests/utils/test_file_managers.py`
- **Responsibility**: Unit tests for all managers (LocalFileManager, TempFileManager) and integration tests for S3/GCS (mocked SDK calls). Tests for FileServingExtension with aiohttp test client. Factory tests.
- **Depends on**: All modules, `pytest`, `pytest-asyncio`, `aiohttp.test_utils`

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_file_metadata_creation` | Module 1 | FileMetadata dataclass instantiation and field access |
| `test_local_list_files` | Module 2 | List files with pattern matching |
| `test_local_upload_download` | Module 2 | Upload file, verify metadata, download and compare |
| `test_local_copy_delete` | Module 2 | Copy file, verify exists, delete, verify gone |
| `test_local_sandboxing_blocks_traversal` | Module 2 | Path traversal (`../`) raises ValueError |
| `test_local_symlink_blocked` | Module 2 | Symlink access denied when `follow_symlinks=False` |
| `test_local_create_from_text` | Module 2 | Create text file, read back, verify encoding |
| `test_local_create_from_bytes` | Module 2 | Create binary file from BytesIO |
| `test_local_exists` | Module 2 | exists() returns True/False correctly |
| `test_local_get_file_metadata` | Module 2 | Metadata fields populated correctly |
| `test_temp_auto_cleanup` | Module 3 | Files removed after context manager exit |
| `test_temp_list_and_create` | Module 3 | Create files in temp, list them |
| `test_temp_download_moves_file` | Module 3 | download_file() moves file out of temp |
| `test_temp_sandboxed` | Module 3 | Cannot escape temp directory |
| `test_s3_list_files_paginated` | Module 4 | Paginated listing returns FileMetadata objects |
| `test_s3_upload_small_file` | Module 4 | Regular upload for files below threshold |
| `test_s3_upload_multipart` | Module 4 | Multipart upload triggered for large files |
| `test_s3_presigned_url` | Module 4 | Presigned URL generation |
| `test_s3_find_files` | Module 4 | Keyword and extension filtering |
| `test_s3_credentials_from_constructor` | Module 4 | Constructor params override navigator.conf |
| `test_s3_credentials_from_conf` | Module 4 | Falls back to AWS_CREDENTIALS |
| `test_gcs_list_files` | Module 5 | List files returns FileMetadata objects |
| `test_gcs_upload_resumable` | Module 5 | Resumable upload for large files |
| `test_gcs_folder_operations` | Module 5 | create/remove/rename folder |
| `test_gcs_signed_url` | Module 5 | Signed URL generation |
| `test_gcs_find_files` | Module 5 | Keyword and extension filtering |
| `test_gcs_three_credential_modes` | Module 5 | Dict, file, default credentials |
| `test_factory_create_local` | Module 7 | Factory creates LocalFileManager |
| `test_factory_create_s3` | Module 7 | Factory creates S3FileManager |
| `test_factory_unknown_type` | Module 7 | Raises ValueError for unknown type |
| `test_lazy_loading` | Module 8 | S3/GCS not imported until accessed |

### Integration Tests
| Test | Description |
|---|---|
| `test_web_serving_local` | FileServingExtension serves local files via aiohttp test client |
| `test_web_serving_range_request` | Range request returns HTTP 206 with correct Content-Range |
| `test_web_serving_404` | Missing file returns 404 |
| `test_web_serving_setup_registers_routes` | setup(app) registers GET route correctly |
| `test_backward_compat_setup` | manager.setup(app) still works (delegates to extension) |
| `test_backward_compat_handle_file` | manager.handle_file(request) still works |

### Test Data / Fixtures
```python
@pytest.fixture
def tmp_dir(tmp_path):
    """Temporary directory with sample files for local manager tests."""
    (tmp_path / "test.txt").write_text("hello world")
    (tmp_path / "data.json").write_text('{"key": "value"}')
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested")
    return tmp_path

@pytest.fixture
def local_manager(tmp_dir):
    """LocalFileManager sandboxed to tmp_dir."""
    return LocalFileManager(base_path=tmp_dir, sandboxed=True)

@pytest.fixture
def temp_manager():
    """TempFileManager with auto-cleanup."""
    return TempFileManager(prefix="test_nav_")

@pytest.fixture
def mock_s3_credentials():
    """Mock AWS credentials dict."""
    return {
        "default": {
            "aws_key": "AKIAEXAMPLE",
            "aws_secret": "secret",
            "region_name": "us-east-1",
            "bucket_name": "test-bucket"
        }
    }
```

---

## 5. Acceptance Criteria

- [ ] `FileManagerInterface` ABC defines all 11 methods (9 abstract + 2 concrete helpers) with correct type hints.
- [ ] `FileMetadata` dataclass has fields: `name`, `path`, `size`, `content_type`, `modified_at`, `url`.
- [ ] `LocalFileManager` passes all unit tests including sandboxing and symlink blocking.
- [ ] `TempFileManager` auto-cleans on context manager exit and `atexit`.
- [ ] `S3FileManager` multipart uploads trigger for files >= 100MB (configurable threshold).
- [ ] `GCSFileManager` resumable uploads trigger for files >= 5MB (configurable threshold).
- [ ] `GCSFileManager` supports folder operations: `create_folder()`, `remove_folder()`, `rename_folder()`, `rename_file()`.
- [ ] All managers implement `find_files(keywords, extension, prefix)`.
- [ ] `FileServingExtension` serves files with Range request support (HTTP 206).
- [ ] Backward compatibility: `manager.setup(app)` and `manager.handle_file(request)` work for GCS, S3, and Temp managers.
- [ ] `FileManagerFactory.create("s3", ...)` returns a correctly configured `S3FileManager`.
- [ ] Cloud managers (S3, GCS) are lazy-loaded — not imported at module load time.
- [ ] S3 credentials accept constructor params with `navigator.conf.AWS_CREDENTIALS` as fallback.
- [ ] All unit tests pass: `pytest tests/utils/test_file_managers.py -v`
- [ ] No breaking changes to existing `from navigator.utils.file import GCSFileManager, S3FileManager, TempFileManager`.

---

## 6. Codebase Contract

### Verified Imports
```python
# Navigator imports — confirmed to exist:
from navigator.conf import AWS_CREDENTIALS            # navigator/utils/file/s3.py:14
from navigator.types import WebApp                     # navigator/types.pyx (WebApp = web.Application)
from navigator.applications.base import BaseApplication # used by all current managers
from navigator.extensions import BaseExtension         # navigator/extensions.py:23
from navconfig.logging import logging                  # used by GCS (gcs.py:15) and S3 (s3.py:12)

# External dependencies — confirmed in current codebase:
import aioboto3                                        # navigator/utils/file/s3.py:11
from google.cloud import storage                       # navigator/utils/file/gcs.py:13
from google.oauth2 import service_account              # navigator/utils/file/gcs.py:14
import google.auth                                     # navigator/utils/file/gcs.py:12
from aiohttp import web                                # navigator/utils/file/gcs.py:11, s3.py:10, tmp.py:11
from botocore.exceptions import ClientError            # ai-parrot s3.py:10

# Current Navigator file manager exports:
from navigator.utils.file import TempFileManager       # navigator/utils/file/__init__.py:1
from navigator.utils.file import GCSFileManager        # navigator/utils/file/__init__.py:2
from navigator.utils.file import S3FileManager         # navigator/utils/file/__init__.py:3
```

### Existing Class Signatures

```python
# navigator/extensions.py:23-67
class BaseExtension(ABC):
    name: str = None                                   # line 29
    app: WebApp = None                                 # line 30
    on_startup: Optional[Callable] = None              # line 33
    on_shutdown: Optional[Callable] = None             # line 36
    on_cleanup: Optional[Callable] = None              # line 39
    on_context: Optional[Callable] = None              # line 42
    middleware: Optional[Callable] = None               # line 45
    def __init__(self, *args, app_name: str = None, **kwargs) -> None:  # line 47
    def setup(self, app: WebApp) -> WebApp:            # line 59
```

```python
# navigator/utils/file/gcs.py:20-79 (CURRENT — will be replaced)
class GCSFileManager:
    def __init__(self, bucket_name: str, route: str = '/data', **kwargs): ...  # line 27
    def list_all_files(self, prefix=None) -> list: ...                         # line 81
    def list_files(self, prefix=None) -> List[str]: ...                        # line 94
    def upload_file(self, source_file_path, destination_blob_name) -> str: ... # line 107
    def upload_file_from_bytes(self, file_obj, dest, content_type='application/zip') -> str: ...  # line 128
    def upload_file_from_string(self, data, destination_blob_name) -> str: ... # line 150
    def delete_file(self, blob_name): ...                                      # line 165
    def find_files(self, keywords=None, extension=None, prefix=None) -> list: ...  # line 375
    def create_folder(self, folder_name): ...                                  # line 405
    def remove_folder(self, folder_name): ...                                  # line 418
    def rename_folder(self, old_folder_name, new_folder_name): ...             # line 431
    def rename_file(self, old_file_name, new_file_name): ...                   # line 449
    def setup(self, app, route='data', base_url=None): ...                     # line 300
    async def handle_file(self, request): ...                                  # line 207
    def get_file_url(self, blob_name, base_url=None, use_signed_url=False, expiration=3600) -> str: ...  # line 330
    def parse_range_header(self, range_header, file_size) -> tuple: ...        # line 276
```

```python
# navigator/utils/file/s3.py:20-64 (CURRENT — will be replaced)
class S3FileManager:
    manager_name: str = 's3file'                                               # line 26
    def __init__(self, bucket_name=None, route='/data', aws_id='default', **kwargs): ...  # line 28
    async def list_files(self, prefix=None) -> AsyncGenerator: ...             # line 66
    async def upload_file(self, source_file_path, destination_key) -> str: ... # line 85
    async def upload_file_from_bytes(self, file_obj, dest, content_type='application/octet-stream') -> str: ...  # line 100
    async def delete_file(self, key): ...                                      # line 126
    async def generate_presigned_url(self, key, expiration=3600) -> str: ...   # line 136
    async def find_files(self, keywords=None, extension=None, prefix=None) -> list: ...  # line 155
    def setup(self, app, route='/data', base_url=None): ...                    # line 235
    async def handle_file(self, request): ...                                  # line 187
```

```python
# navigator/utils/file/tmp.py:16-128 (CURRENT — will be replaced)
class TempFileManager:
    def __init__(self): ...                                                    # line 22
    @staticmethod
    def create_temp_file(suffix='', prefix='tmp', dir=None) -> str: ...        # line 28
    @staticmethod
    def remove_temp_file(file_path): ...                                       # line 37
    async def handle_file(self, request): ...                                  # line 46
    def setup(self, app, route='data', base_url=None): ...                     # line 70
    def get_file_url(self, temp_file_path, base_url=None) -> str: ...          # line 100
```

#### AI-Parrot Source Signatures (to port)

```python
# ai-parrot: parrot/interfaces/file/abstract.py:8-76
@dataclass
class FileMetadata:
    name: str; path: str; size: int
    content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]

class FileManagerInterface(ABC):
    # 9 abstract + 2 concrete methods (see Section 2 New Public Interfaces)
```

```python
# ai-parrot: parrot/interfaces/file/local.py:13-73
class LocalFileManager(FileManagerInterface):
    def __init__(self, base_path=None, create_base=True, follow_symlinks=False, sandboxed=True): ...
    def _resolve_path(self, path: str) -> Path: ...  # sandbox enforcement
    def _get_file_metadata(self, path: Path) -> FileMetadata: ...
    # All FileManagerInterface methods implemented via asyncio.to_thread()
```

```python
# ai-parrot: parrot/interfaces/file/tmp.py:15-58
class TempFileManager(FileManagerInterface):
    def __init__(self, prefix="ai_parrot_", cleanup_on_exit=True, cleanup_on_delete=True): ...
    def cleanup(self): ...
    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...
    def _resolve_path(self, path: str) -> Path: ...
```

```python
# ai-parrot: parrot/interfaces/file/s3.py:15-55
class S3FileManager(FileManagerInterface):
    MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB, line 19
    MULTIPART_CHUNKSIZE = 10 * 1024 * 1024   # 10MB, line 20
    MAX_CONCURRENCY = 10                     # line 21
    def __init__(self, bucket_name=None, aws_id='default', region_name=None,
                 prefix="", multipart_threshold=None, multipart_chunksize=None,
                 max_concurrency=None, **kwargs): ...
```

```python
# ai-parrot: parrot/interfaces/file/gcs.py:16-51
class GCSFileManager(FileManagerInterface):
    RESUMABLE_THRESHOLD = 5 * 1024 * 1024    # 5MB, line 20
    CHUNK_SIZE = 256 * 1024                  # 256KB, line 21
    def __init__(self, bucket_name, prefix="", json_credentials=None,
                 credentials=None, scopes=None, project=None,
                 resumable_threshold=None, **kwargs): ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FileServingExtension` | `BaseExtension.setup()` | inheritance | `navigator/extensions.py:59` |
| `FileServingExtension` | `BaseApplication.get_app()` | method call in setup | `navigator/extensions.py:60` |
| `S3FileManager` | `AWS_CREDENTIALS` | dict lookup (default) | `navigator/conf` via `s3.py:14` |
| All managers | `navconfig.logging.logging` | logger creation | `gcs.py:15`, `s3.py:12` |
| `__init__.py` | Lazy loading | `__getattr__` + `importlib` | Pattern from ai-parrot `__init__.py:29-35` |

### Does NOT Exist (Anti-Hallucination)

**In Navigator (does NOT exist yet — will be created):**
- ~~`navigator.utils.file.abstract`~~ — module does not exist
- ~~`navigator.utils.file.local`~~ — module does not exist
- ~~`navigator.utils.file.web`~~ — module does not exist
- ~~`navigator.utils.file.factory`~~ — module does not exist
- ~~`navigator.utils.file.FileManagerInterface`~~ — class does not exist
- ~~`navigator.utils.file.FileMetadata`~~ — class does not exist
- ~~`navigator.utils.file.LocalFileManager`~~ — class does not exist
- ~~`navigator.utils.file.FileServingExtension`~~ — class does not exist
- ~~`navigator.utils.file.FileManagerFactory`~~ — class does not exist

**Methods that do NOT exist in current Navigator managers:**
- ~~`GCSFileManager.download_file()`~~ — not implemented
- ~~`GCSFileManager.copy_file()`~~ — not implemented
- ~~`GCSFileManager.exists()`~~ — not implemented
- ~~`GCSFileManager.get_file_metadata()`~~ — not implemented
- ~~`GCSFileManager.create_file()`~~ — not implemented
- ~~`S3FileManager.download_file()`~~ — not implemented
- ~~`S3FileManager.copy_file()`~~ — not implemented
- ~~`S3FileManager.exists()`~~ — not implemented
- ~~`S3FileManager.get_file_metadata()`~~ — not implemented
- ~~`S3FileManager.create_file()`~~ — not implemented
- ~~`TempFileManager.upload_file()`~~ — not implemented
- ~~`TempFileManager.list_files()`~~ — not implemented
- ~~`TempFileManager.download_file()`~~ — not implemented
- ~~`TempFileManager.exists()`~~ — not implemented

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **ABC pattern**: `FileManagerInterface` as the contract — all managers inherit it.
- **Async-first**: All public methods `async def`. Blocking calls via `asyncio.to_thread()`.
- **Lazy loading**: Cloud managers imported only when accessed via `__getattr__` in `__init__.py`.
- **Sandboxing**: `_resolve_path()` method validates paths stay within base directory.
- **Logging**: Use `navconfig.logging.logging.getLogger('storage.<ManagerName>')`.
- **Config**: Constructor params take precedence; `navigator.conf` values are fallbacks.
- **Backward compat**: Each manager retains `setup(app, route, base_url)` and `handle_file(request)` that internally create/use a `FileServingExtension`.

### Known Risks / Gotchas
- **GCS SDK is synchronous**: Every GCS operation must be wrapped in `asyncio.to_thread()`. This includes `bucket.list_blobs()`, `blob.upload_from_filename()`, `blob.download_to_filename()`, etc. Missing a wrapper will block the event loop.
- **S3 multipart abort**: If a multipart upload fails mid-way, the incomplete upload must be explicitly aborted via `abort_multipart_upload()` to avoid orphaned S3 parts and billing.
- **TempFileManager prefix change**: AI-Parrot uses `"ai_parrot_"` prefix; Navigator should use `"navigator_"` or make it configurable.
- **`find_files()` not in AI-Parrot's ABC**: This is a Navigator addition. Add it to the interface with a default implementation that calls `list_files()` + filtering, so managers can override with optimized versions.
- **BaseExtension registration**: `BaseExtension.setup()` stores `self` in `app[self.name]` and `app.extensions[self.name]`. `FileServingExtension` must set a unique `name` per manager instance to avoid collisions when multiple managers serve on different routes.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aioboto3` | existing | Async S3 client for S3FileManager |
| `google-cloud-storage` | existing | GCS client for GCSFileManager |
| `google-auth` | existing | GCS credential handling |
| `aiohttp` | existing | Web serving (FileServingExtension) |
| `navconfig` | existing | Configuration and logging |
| `botocore` | existing (transitive) | `ClientError` for S3 error handling |

No new dependencies required.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules 2-5 (managers) share the abstract interface (Module 1) and the `__init__.py` (Module 8). Module 6 (web) depends on at least one manager. Sequential execution avoids merge conflicts in shared files.
- **Cross-feature dependencies**: None. No in-flight specs touch `navigator/utils/file/`.
- **Recommended worktree creation**:
  ```bash
  git worktree add -b feat-002-file-interfaces \
    .claude/worktrees/feat-002-file-interfaces HEAD
  ```

---

## 8. Open Questions

- [ ] Should `find_files()` be added to `FileManagerInterface` as an abstract method, or as a concrete method with a default filtering implementation? — *Owner: Jesus*: added
- [ ] Should GCS folder operations (`create_folder`, `remove_folder`, `rename_folder`, `rename_file`) be part of `FileManagerInterface` or remain GCS-specific methods? — *Owner: Jesus*: be part of FileManagerInterface
- [ ] Exact structure of `AWS_CREDENTIALS` in `navigator.conf` — it's imported in s3.py but defined in navconfig, not in conf.py directly. Need to verify dict shape. — *Owner: Jesus*: is a dictionary: AWS_CREDENTIALS = {
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
    },
- [ ] Should `FileServingExtension` extend `BaseExtension` or be a standalone class? BaseExtension provides `setup(app)` + signal registration. — *Owner: Jesus*: extend BaseExtension.
- [ ] When AI-Parrot switches to `from navigator.utils.file import ...`, should `parrot/interfaces/file/` become a re-export shim or be removed? (Out of scope for this spec, but affects planning.) — *Owner: Jesus*: re-export shim

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Jesus Lara | Initial draft from brainstorm |
