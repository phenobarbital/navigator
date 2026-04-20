# TASK-015: Web Serving Layer (FileServingExtension)

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-010
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 6. New code — decouples HTTP file serving
(route registration, streaming, Range requests) from managers into `FileServingExtension`.
Extracted and generalized from Navigator's current `handle_file()` implementations.

---

## Scope

- Create `navigator/utils/file/web.py` with `FileServingExtension`.
- Follow `BaseExtension` pattern for aiohttp integration.
- `setup(app)`: register GET route `{route}/{filepath:.*}`.
- `handle_file(request)`: stream files from any `FileManagerInterface`.
  - Range requests (HTTP 206). Caching headers. Content-Disposition.
  - Path sanitization. 404 for missing files.
- `manager_name` param for backward compat app context registration.
- Handle `BaseApplication` unwrapping.

**NOT in scope**: Manager implementations, factory, `__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/web.py` | CREATE | FileServingExtension |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface, FileMetadata  # TASK-010
from ...extensions import BaseExtension                   # navigator/extensions.py:23
from ...types import WebApp                               # navigator/types.pyx
from ...applications.base import BaseApplication
from aiohttp import web
import os
from pathlib import PurePath
from datetime import datetime, timedelta, timezone
from typing import Optional
```

### Existing Signatures to Use
```python
# navigator/extensions.py:23-67
class BaseExtension(ABC):
    name: str = None                                # line 29
    app: WebApp = None                              # line 30
    def __init__(self, *args, app_name=None, **kwargs): ...  # line 47
    def setup(self, app: WebApp) -> WebApp: ...     # line 59

# Current handle_file patterns to generalize:
# GCS: streaming + Range (gcs.py:207-298)
# S3: streaming (s3.py:187-233)
# Tmp: FileResponse (tmp.py:46-68)
```

### Does NOT Exist
- ~~`navigator.utils.file.web`~~ — this task creates it
- ~~`BaseExtension.handle_file()`~~ — not on BaseExtension
- ~~`FileManagerInterface.stream_file()`~~ — not in interface

---

## Implementation Notes

### Key Constraints
- Works with ANY `FileManagerInterface` — not coupled to specific backends.
- Range request: parse `bytes=start-end`, return 206 with Content-Range.
- Stream in 1MB chunks. Caching headers (7-day expires, Cache-Control).
- `manager_name` enables `app["gcsfile"]`/`app["s3file"]`/`app["tempfile"]`.
- Path sanitization via `PurePath` to prevent traversal.

### References
- `navigator/utils/file/gcs.py:207-298` — handle_file + parse_range_header
- `navigator/utils/file/s3.py:187-233` — handle_file
- `navigator/extensions.py:23-80` — BaseExtension pattern

---

## Acceptance Criteria

- [ ] `navigator/utils/file/web.py` with `FileServingExtension`
- [ ] Follows BaseExtension pattern
- [ ] `setup(app)` registers GET route
- [ ] `handle_file()` streams from any FileManagerInterface
- [ ] Range requests return HTTP 206
- [ ] Caching headers set
- [ ] `manager_name` stores manager in app context
- [ ] 404 for missing files
- [ ] Path sanitization

---

## Agent Instructions

When you pick up this task:
1. Read spec + current handler implementations in gcs.py, s3.py, tmp.py
2. Read BaseExtension in navigator/extensions.py
3. Verify TASK-010 completed
4. Implement per scope
5. Move to `tasks/completed/` and update index

---

## Completion Note
FileServingExtension created extending BaseExtension. setup() registers GET route. handle_file() streams from any FileManagerInterface. Range requests (HTTP 206) supported. Caching headers, path sanitization, 404 for missing files. manager_name enables per-manager app context keys.
