# TASK-011: Local File Manager

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-010
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 2. Port AI-Parrot's `LocalFileManager` into Navigator.
Handles local disk operations with sandboxing, symlink control, all I/O via `asyncio.to_thread()`.

---

## Scope

- Create `navigator/utils/file/local.py` with `LocalFileManager(FileManagerInterface)`.
- Implement all abstract methods + `find_files()` override.
- Sandboxing via `_resolve_path()` — block path traversal by default.
- `follow_symlinks` control (default: blocked).
- All blocking I/O in `asyncio.to_thread()`.
- `mimetypes.guess_type()` for content type. `file://` URIs in metadata.
- Add `manager_name = 'localfile'` class attribute.

**NOT in scope**: Web serving, factory, `__init__.py`, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/local.py` | CREATE | LocalFileManager implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface, FileMetadata  # TASK-010
import os, shutil, mimetypes, fnmatch, asyncio
from pathlib import Path
from typing import BinaryIO, Optional, List, Union
from datetime import datetime
from io import BytesIO, StringIO
from navconfig.logging import logging  # verified: navigator/utils/file/gcs.py:15
```

### Existing Signatures to Use
```python
# AI-Parrot source (parrot/interfaces/file/local.py:13-73):
class LocalFileManager(FileManagerInterface):
    def __init__(self, base_path=None, create_base=True, follow_symlinks=False, sandboxed=True): ...
    def _resolve_path(self, path: str) -> Path: ...  # sandbox enforcement
    def _get_file_metadata(self, path: Path) -> FileMetadata: ...
```

### Does NOT Exist
- ~~`navigator.utils.file.local`~~ — this task creates it
- ~~`navigator.utils.file.LocalFileManager`~~ — this task creates it

---

## Implementation Notes

### Key Constraints
- ALL file I/O via `asyncio.to_thread()`.
- Sandbox default-on: `_resolve_path()` raises `ValueError` for traversal.
- `follow_symlinks=False`: skip symlinks in listing, reject in resolve.
- `get_file_url()` returns `file://{resolved_path}`.
- Logger: `logging.getLogger('navigator.storage.Local')`.

### References
- `parrot/interfaces/file/local.py` — full source to port (lines 13-284)

---

## Acceptance Criteria

- [ ] `navigator/utils/file/local.py` exists with `LocalFileManager`
- [ ] All 12 interface methods implemented
- [ ] Sandboxing blocks `../` traversal
- [ ] Symlinks blocked by default
- [ ] All I/O via `asyncio.to_thread()`
- [ ] `list_files()` supports glob patterns
- [ ] Content type via `mimetypes.guess_type()`

---

## Agent Instructions

When you pick up this task:
1. Read spec + AI-Parrot source `parrot/interfaces/file/local.py`
2. Verify TASK-010 completed (abstract.py exists)
3. Implement per scope
4. Move to `tasks/completed/` and update index

---

## Completion Note
LocalFileManager implemented with sandboxing, symlink control, asyncio.to_thread() for all I/O, fnmatch patterns, and mimetypes content-type detection. find_files() is overridden with recursive rglob support.
