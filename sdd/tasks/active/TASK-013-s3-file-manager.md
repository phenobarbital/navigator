# TASK-013: S3 File Manager

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-010
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 4. Replaces Navigator's `S3FileManager` with a version
implementing `FileManagerInterface`, adding multipart uploads (100MB threshold, 10MB chunks,
10 concurrent), FileMetadata returns, and configurable credentials with `navigator.conf.AWS_CREDENTIALS` fallback.

---

## Scope

- Rewrite `navigator/utils/file/s3.py` with `S3FileManager(FileManagerInterface)`.
- Multipart uploads: 100MB threshold, 10MB chunks, semaphore-based concurrency (10).
- Abort incomplete multipart uploads on failure.
- Credentials: constructor params override `AWS_CREDENTIALS` from `navigator.conf`.
- All abstract methods + `find_files()` override (server-side prefix + client filtering).
- Paginated listing via S3 paginator. Presigned URLs. Prefix management.
- Preserve `manager_name = 's3file'`.

**NOT in scope**: Web serving, factory, `__init__.py`, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/s3.py` | REPLACE | Rewritten S3FileManager |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface, FileMetadata  # TASK-010
import aioboto3                                           # navigator/utils/file/s3.py:11
from botocore.exceptions import ClientError               # ai-parrot s3.py:10
from ...conf import AWS_CREDENTIALS                       # navigator/utils/file/s3.py:14
from navconfig.logging import logging                     # navigator/utils/file/s3.py:12
import asyncio, mimetypes, fnmatch, contextlib
from pathlib import Path
from typing import BinaryIO, Optional, List, Union
from datetime import datetime
from io import BytesIO, StringIO
```

### Existing Signatures to Use
```python
# Current credentials pattern (navigator/utils/file/s3.py:47-64):
credentials = AWS_CREDENTIALS.get(aws_id, 'default')
# dict: {"aws_key", "aws_secret", "region_name"?, "bucket_name"?}
self.session = aioboto3.Session(**self.aws_config)

# AI-Parrot multipart (parrot/interfaces/file/s3.py:19-21):
MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB
MULTIPART_CHUNKSIZE = 10 * 1024 * 1024   # 10MB
MAX_CONCURRENCY = 10
```

### Does NOT Exist
- ~~`S3FileManager.download_file()`~~ — not in current Navigator
- ~~`S3FileManager.copy_file()`~~ — not in current Navigator
- ~~`S3FileManager.exists()`~~ — not in current Navigator
- ~~`S3FileManager.get_file_metadata()`~~ — not in current Navigator

---

## Implementation Notes

### Key Constraints
- All S3 calls natively async via aioboto3 — no `to_thread()`.
- Multipart: `create_multipart_upload()` + concurrent `upload_part()` (Semaphore) + `complete_multipart_upload()`.
- On failure: MUST `abort_multipart_upload()` to prevent orphaned parts.
- Credentials: constructor `credentials` kwarg > `AWS_CREDENTIALS.get(aws_id)`.
- Prefix: `self.prefix` prepended to all keys; stripped from FileMetadata.
- Logger: `logging.getLogger('navigator.storage.S3')`.

### References
- `parrot/interfaces/file/s3.py` — full source (lines 15-511)
- `navigator/utils/file/s3.py` — current version (lines 20-255)

---

## Acceptance Criteria

- [ ] Rewritten with `FileManagerInterface`
- [ ] All 12 interface methods + `find_files()`
- [ ] Multipart for files >= 100MB (configurable)
- [ ] Concurrent part uploads with semaphore
- [ ] Failed multiparts aborted
- [ ] Credentials: constructor params with AWS_CREDENTIALS fallback
- [ ] Paginated listing, presigned URLs, prefix management
- [ ] `manager_name = 's3file'` preserved

---

## Agent Instructions

When you pick up this task:
1. Read spec + both AI-Parrot and Navigator S3 source files
2. Verify TASK-010 completed
3. Implement per scope — pay special attention to multipart abort logic
4. Move to `tasks/completed/` and update index

---

## Completion Note
*(Agent fills this in when done)*
