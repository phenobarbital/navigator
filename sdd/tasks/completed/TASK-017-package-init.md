# TASK-017: Package Init & Backward Compatibility

**Feature**: FEAT-002 — File Manager Interfaces Modernization
**Spec**: `sdd/specs/file-interfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016
**Assigned-to**: unassigned

---

## Context

Implements Spec Section 3, Module 8. Integration task: rewrites `__init__.py` with lazy
loading exports and adds backward-compatible `setup()`/`handle_file()` to each manager.

---

## Scope

- Rewrite `navigator/utils/file/__init__.py`:
  - Eager: FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager, FileServingExtension, FileManagerFactory
  - Lazy (`__getattr__`): S3FileManager, GCSFileManager
  - `__all__` with all 8 public names
- Add backward-compat methods to each manager (MODIFY existing files):
  - `setup(app, route, base_url)`: creates `FileServingExtension` internally
  - `handle_file(request)`: delegates to extension
  - Manager names: GCS=`"gcsfile"`, S3=`"s3file"`, Tmp=`"tempfile"`, Local=`"localfile"`

**NOT in scope**: Manager core implementations (done), tests (TASK-018).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/utils/file/__init__.py` | REPLACE | New exports + lazy loading |
| `navigator/utils/file/local.py` | MODIFY | Add setup() + handle_file() |
| `navigator/utils/file/tmp.py` | MODIFY | Add setup() + handle_file() |
| `navigator/utils/file/s3.py` | MODIFY | Add setup() + handle_file() |
| `navigator/utils/file/gcs.py` | MODIFY | Add setup() + handle_file() |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Lazy loading pattern (from ai-parrot __init__.py:23-35):
import importlib, sys
_LAZY_MANAGERS = {"S3FileManager": ".s3", "GCSFileManager": ".gcs"}
def __getattr__(name): ...

# Current setup() signatures to preserve:
# GCS: setup(self, app, route='data', base_url=None)      # gcs.py:300
# S3:  setup(self, app, route='/data', base_url=None)      # s3.py:235
# Tmp: setup(self, app, route='data', base_url=None)       # tmp.py:70

# App context keys: "gcsfile", "s3file", "tempfile"
```

### Does NOT Exist
- ~~`FileManagerInterface.setup()`~~ — NOT in ABC; per-manager backward compat only
- ~~`FileManagerInterface.handle_file()`~~ — NOT in ABC

---

## Acceptance Criteria

- [ ] `from navigator.utils.file import GCSFileManager, S3FileManager, TempFileManager` works
- [ ] `from navigator.utils.file import FileManagerInterface, FileMetadata, LocalFileManager` works
- [ ] `from navigator.utils.file import FileServingExtension, FileManagerFactory` works
- [ ] S3/GCS lazy-loaded (not imported at module load)
- [ ] `manager.setup(app)` works and registers in app context
- [ ] `manager.handle_file(request)` delegates to FileServingExtension
- [ ] `__all__` lists all 8 names

---

## Agent Instructions

When you pick up this task:
1. Verify ALL previous tasks completed (TASK-010 through TASK-016)
2. Read current `__init__.py` and each manager's source
3. Implement per scope
4. Test imports manually
5. Move to `tasks/completed/` and update index

---

## Completion Note
__init__.py rewritten: eager exports for Local/Temp/Abstract/Web/Factory; S3/GCS lazy-loaded via __getattr__ + importlib. __all__ lists all 8 public names. Backward-compat setup()/handle_file() added to all 4 managers, delegating to FileServingExtension.
