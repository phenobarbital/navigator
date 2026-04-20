# TASK-010: Abstract Interface (FileManagerInterface + FileMetadata)

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task — all other tasks depend on this. Implements Spec Section 3, Module 1.
Port `FileManagerInterface` ABC and `FileMetadata` dataclass from AI-Parrot's
`parrot/interfaces/file/abstract.py`, adding `find_files()` as a concrete method.

---

## Scope

- Create `navigator/utils/file/abstract.py` with:
  - `FileMetadata` dataclass (name, path, size, content_type, modified_at, url)
  - `FileManagerInterface` ABC with 9 abstract methods + 3 concrete helpers
- Add `find_files()` as concrete method: calls `list_files()` + filters by keywords/extension/prefix.
- stdlib only — no external dependencies.

**NOT in scope**: Manager implementations, web layer, factory, tests, `__init__.py` changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/abstract.py` | CREATE | ABC + FileMetadata dataclass |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only:
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List, Union
from io import BytesIO, StringIO
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
```

### Existing Signatures to Use
```python
# Source: ai-parrot parrot/interfaces/file/abstract.py:8-76
@dataclass
class FileMetadata:
    name: str; path: str; size: int
    content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]

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
    async def create_from_text(self, path, text, encoding="utf-8") -> bool: ...  # concrete
    async def create_from_bytes(self, path, data) -> bool: ...  # concrete
```

### Does NOT Exist
- ~~`navigator.utils.file.abstract`~~ — does not exist yet (this task creates it)
- ~~`navigator.utils.file.FileManagerInterface`~~ — does not exist yet
- ~~`navigator.utils.file.FileMetadata`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
Port from `parrot/interfaces/file/abstract.py`. Add `find_files()` as concrete:
```python
async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:
    files = await self.list_files(path=prefix or "")
    results = []
    for f in files:
        if extension and not f.name.endswith(extension):
            continue
        if keywords:
            kw_list = [keywords] if isinstance(keywords, str) else keywords
            if not all(kw in f.name for kw in kw_list):
                continue
        results.append(f)
    return results
```

### Key Constraints
- stdlib only. Use `@dataclass` not Pydantic. All abstract methods `async def`.
- `BinaryIO | Path` union syntax (Python 3.10+).

---

## Acceptance Criteria

- [ ] `navigator/utils/file/abstract.py` exists
- [ ] `FileMetadata` has 6 fields: name, path, size, content_type, modified_at, url
- [ ] `FileManagerInterface` has 9 abstract + 3 concrete methods
- [ ] `find_files()` is concrete with default filtering
- [ ] No external dependencies
- [ ] `from navigator.utils.file.abstract import FileManagerInterface, FileMetadata` works

---

## Agent Instructions

When you pick up this task:
1. Read the spec for full context
2. Read AI-Parrot source: `parrot/interfaces/file/abstract.py`
3. Update status in `tasks/.index.json` -> `"in-progress"`
4. Implement per scope
5. Move to `tasks/completed/` and update index -> `"done"`

---

## Completion Note
*(Agent fills this in when done)*
