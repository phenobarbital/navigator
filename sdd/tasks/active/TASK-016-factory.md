# TASK-016: File Manager Factory

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-010, TASK-011, TASK-012, TASK-013, TASK-014
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 7. `FileManagerFactory` provides runtime
creation of file managers by type string with lazy imports for cloud managers.

---

## Scope

- Create `navigator/utils/file/factory.py` with `FileManagerFactory`.
- `create(manager_type, **kwargs)` -> `FileManagerInterface`.
- Types: `"local"`, `"temp"`, `"s3"`, `"gcs"`.
- Lazy import cloud managers via `importlib`.
- `ValueError` for unknown types.

**NOT in scope**: Manager implementations, web layer, `__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/factory.py` | CREATE | FileManagerFactory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import FileManagerInterface
# Managers imported lazily via importlib
```

### Does NOT Exist
- ~~`navigator.utils.file.factory`~~ — this task creates it

---

## Acceptance Criteria

- [ ] `create("local")` returns `LocalFileManager`
- [ ] `create("temp")` returns `TempFileManager`
- [ ] `create("s3", ...)` returns `S3FileManager`
- [ ] `create("gcs", ...)` returns `GCSFileManager`
- [ ] `create("unknown")` raises `ValueError`
- [ ] Cloud managers lazy-imported

---

## Agent Instructions

When you pick up this task:
1. Verify TASK-010 through TASK-014 completed
2. Implement per scope
3. Move to `tasks/completed/` and update index

---

## Completion Note
*(Agent fills this in when done)*
