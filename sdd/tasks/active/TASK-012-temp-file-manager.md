# TASK-012: Temp File Manager

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-010
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 3. Replaces Navigator's current `TempFileManager`
with a version implementing `FileManagerInterface`, adding auto-cleanup, context
manager support, sandboxing, and move semantics. Ported from AI-Parrot's `tmp.py`.

---

## Scope

- Rewrite `navigator/utils/file/tmp.py` with `TempFileManager(FileManagerInterface)`.
- Auto-cleanup via `atexit`, `__del__`, and async context manager.
- Sandboxed to temp directory. Move semantics for `download_file()`.
- `asyncio.to_thread()` for blocking I/O.
- Preserve backward-compat: `create_temp_file()` and `remove_temp_file()` as static methods.
- Default prefix: `"navigator_"`. Add `manager_name = 'tempfile'`.

**NOT in scope**: Web serving (`setup()`/`handle_file()`), factory, `__init__.py`, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/tmp.py` | REPLACE | Rewritten TempFileManager |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface, FileMetadata  # TASK-010
import contextlib, tempfile, shutil, mimetypes, fnmatch, asyncio, atexit, os
from pathlib import Path
from typing import BinaryIO, Optional, List, Union
from datetime import datetime
from io import BytesIO, StringIO
from navconfig.logging import logging  # verified: navigator/utils/file/gcs.py:15
```

### Existing Signatures to Use
```python
# CURRENT backward-compat methods to preserve (navigator/utils/file/tmp.py):
@staticmethod
def create_temp_file(suffix='', prefix='tmp', dir=None) -> str: ...  # line 28
@staticmethod
def remove_temp_file(file_path): ...  # line 37

# AI-Parrot source (parrot/interfaces/file/tmp.py:15-58):
class TempFileManager(FileManagerInterface):
    def __init__(self, prefix="ai_parrot_", cleanup_on_exit=True, cleanup_on_delete=True): ...
    def cleanup(self): ...
    async def __aenter__(self): ...
    async def __aexit__(self, ...): ...
```

### Does NOT Exist
- ~~`TempFileManager.upload_file()`~~ — not in current Navigator version
- ~~`TempFileManager.list_files()`~~ — not in current Navigator version

---

## Implementation Notes

### Key Constraints
- Prefix: `"navigator_"` (not `"ai_parrot_"`).
- `download_file()` MOVES file out of temp. `copy_file()`: internal=copy, external=move.
- `cleanup()` suppresses errors. Backward compat statics preserved.
- Logger: `logging.getLogger('navigator.storage.Temp')`.

### References
- `parrot/interfaces/file/tmp.py` — full source (lines 15-309)
- `navigator/utils/file/tmp.py` — current version (lines 16-128)

---

## Acceptance Criteria

- [ ] Rewritten with `FileManagerInterface`
- [ ] All 12 interface methods implemented
- [ ] Auto-cleanup on context manager exit, atexit, __del__
- [ ] `download_file()` moves files out
- [ ] Sandboxing prevents traversal
- [ ] `create_temp_file()` / `remove_temp_file()` backward compat
- [ ] Default prefix `"navigator_"`

---

## Agent Instructions

When you pick up this task:
1. Read spec + both AI-Parrot and Navigator source files
2. Verify TASK-010 completed
3. Implement per scope
4. Move to `tasks/completed/` and update index

---

## Completion Note
*(Agent fills this in when done)*
