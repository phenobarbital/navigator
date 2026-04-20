# TASK-018: Tests

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3 Module 9 and Section 4 (Test Specification).
Comprehensive test suite: unit tests for Local/Temp (real FS), mocked S3/GCS,
integration tests for web layer with aiohttp test client, factory + init tests.

---

## Scope

- Create test files:
  - `tests/utils/test_file_abstract.py` — FileMetadata, ABC cannot instantiate
  - `tests/utils/test_file_local.py` — sandboxing, CRUD, symlinks, patterns
  - `tests/utils/test_file_temp.py` — cleanup, context manager, move semantics
  - `tests/utils/test_file_s3.py` — mocked aioboto3, multipart, credentials
  - `tests/utils/test_file_gcs.py` — mocked GCS SDK, resumable, folder ops
  - `tests/utils/test_file_web.py` — aiohttp test client, Range, 404
  - `tests/utils/test_file_factory.py` — all types, unknown error
  - `tests/utils/test_file_init.py` — imports, lazy loading
- Use `pytest` + `pytest-asyncio`, `unittest.mock`, `aiohttp.test_utils`.
- At least 30 test cases total.

**NOT in scope**: Performance benchmarks, real cloud E2E tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/utils/__init__.py` | CREATE (if needed) | Package marker |
| `tests/utils/test_file_abstract.py` | CREATE | ABC tests |
| `tests/utils/test_file_local.py` | CREATE | Local manager tests |
| `tests/utils/test_file_temp.py` | CREATE | Temp manager tests |
| `tests/utils/test_file_s3.py` | CREATE | S3 tests (mocked) |
| `tests/utils/test_file_gcs.py` | CREATE | GCS tests (mocked) |
| `tests/utils/test_file_web.py` | CREATE | Web serving tests |
| `tests/utils/test_file_factory.py` | CREATE | Factory tests |
| `tests/utils/test_file_init.py` | CREATE | Import + lazy loading tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.utils.file import (
    FileManagerInterface, FileMetadata,
    LocalFileManager, TempFileManager,
    S3FileManager, GCSFileManager,
    FileServingExtension, FileManagerFactory,
)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
```

### Does NOT Exist
- ~~`navigator.utils.file.test_utils`~~ — no test utilities module
- ~~`navigator.utils.file.mock`~~ — no mock module

---

## Acceptance Criteria

- [ ] All test files created
- [ ] `source .venv/bin/activate && pytest tests/utils/test_file_*.py -v` passes
- [ ] Local/Temp tested on real FS (tmp_path)
- [ ] S3/GCS mocked — no real cloud calls
- [ ] Web layer tested with aiohttp test client
- [ ] Range request test verifies HTTP 206
- [ ] Sandboxing tests verify traversal blocked
- [ ] Backward compat: setup()/handle_file() tested
- [ ] Lazy loading verified
- [ ] At least 30 test cases total

---

## Agent Instructions

When you pick up this task:
1. Verify ALL tasks (010-017) completed
2. Read each module to understand actual signatures
3. Check test directory structure: `ls tests/`
4. Implement all test files
5. Run: `source .venv/bin/activate && pytest tests/utils/test_file_*.py -v`
6. Fix failures until all pass
7. Move to `tasks/completed/` and update index

---

## Completion Note
*(Agent fills this in when done)*
