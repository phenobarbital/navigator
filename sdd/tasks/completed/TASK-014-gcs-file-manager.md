# TASK-014: GCS File Manager

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-010
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 5. Replaces Navigator's `GCSFileManager` with a version
implementing `FileManagerInterface`, adding resumable uploads (5MB threshold), async wrapping
via `asyncio.to_thread()`, and all missing interface methods. Preserves folder operations.

---

## Scope

- Rewrite `navigator/utils/file/gcs.py` with `GCSFileManager(FileManagerInterface)`.
- Resumable uploads: 5MB threshold, 256KB chunks.
- Wrap ALL `google-cloud-storage` SDK calls in `asyncio.to_thread()`.
- Three credential modes: dict, file path, `google.auth.default()`.
- All abstract methods + GCS-specific: `create_folder()`, `remove_folder()`, `rename_folder()`, `rename_file()`.
- `find_files()` override. Signed URLs (v4) + app-served URLs. Prefix management.
- Add `manager_name = 'gcsfile'`.

**NOT in scope**: Web serving (`setup()`/`handle_file()`/Range requests), factory, `__init__.py`, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/gcs.py` | REPLACE | Rewritten GCSFileManager |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface, FileMetadata  # TASK-010
import google.auth                                        # gcs.py:12
from google.cloud import storage                          # gcs.py:13
from google.oauth2 import service_account                 # gcs.py:14
from navconfig.logging import logging                     # gcs.py:15
import asyncio, mimetypes, fnmatch
from pathlib import Path, PurePath
from typing import BinaryIO, Optional, List, Union
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from urllib.parse import quote
```

### Existing Signatures to Use
```python
# Current folder ops (navigator/utils/file/gcs.py):
def create_folder(self, folder_name): ...    # line 405
def remove_folder(self, folder_name): ...    # line 418
def rename_folder(self, old, new): ...       # line 431
def rename_file(self, old, new): ...         # line 449

# Credentials (gcs.py:47-75): json_credentials | file | google.auth.default()

# AI-Parrot (parrot/interfaces/file/gcs.py:20-21):
RESUMABLE_THRESHOLD = 5 * 1024 * 1024  # 5MB
CHUNK_SIZE = 256 * 1024                # 256KB
```

### Does NOT Exist
- ~~`GCSFileManager.download_file()`~~ — not in current Navigator
- ~~`GCSFileManager.copy_file()`~~ — not in current Navigator
- ~~`GCSFileManager.exists()`~~ — not in current Navigator

---

## Implementation Notes

### Key Constraints
- ALL google-cloud-storage calls via `asyncio.to_thread()` — never block event loop.
- Folder ops are GCS-specific (not in ABC). Credential init is synchronous in `__init__`.
- `get_file_url()` dual mode: signed URL vs app-served URL (preserve current behavior).
- Prefix: `_prefixed(key)` / `_unprefixed(key)`.
- Logger: `logging.getLogger('navigator.storage.GCS')`.

### References
- `parrot/interfaces/file/gcs.py` — full source (lines 16-378)
- `navigator/utils/file/gcs.py` — current version with folder ops (lines 20-459)

---

## Acceptance Criteria

- [ ] Rewritten with `FileManagerInterface`
- [ ] All 12 interface methods + `find_files()`
- [ ] Resumable uploads for files >= 5MB
- [ ] All GCS SDK calls via `asyncio.to_thread()`
- [ ] Three credential modes
- [ ] Folder ops: create/remove/rename folder, rename file
- [ ] Signed URLs (v4) + app-served URLs
- [ ] Prefix management
- [ ] `manager_name = 'gcsfile'`

---

## Agent Instructions

When you pick up this task:
1. Read spec + both AI-Parrot and Navigator GCS source files
2. Verify TASK-010 completed
3. Implement — pay attention to wrapping ALL SDK calls in to_thread()
4. Move to `tasks/completed/` and update index

---

## Completion Note
GCSFileManager rewritten implementing FileManagerInterface. All GCS SDK calls wrapped in asyncio.to_thread(). Resumable uploads for files >= 5MB. Three credential modes (json dict, file path, ADC). Folder ops (create/remove/rename_folder, rename_file). Signed URLs v4. Prefix management. manager_name=gcsfile.
