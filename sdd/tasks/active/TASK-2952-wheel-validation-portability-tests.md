# TASK-2952: Add wheel validation and portability tests

**Feature**: FEAT-007 — Navigator Wheel Build Infrastructure Refactor
**Spec**: `sdd/specs/wheel-build-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2950, TASK-2951
**Assigned-to**: unassigned

---

## Context

Implement Module 3. The release gate must verify wheel filenames, platform
tags, and compiled extension contents without installing the full optional
dependency graph. The import smoke path must create the navconfig project
environment before importing modules that legitimately need configuration.

## Scope

- Add reusable pure-Python helpers for parsing wheel filenames/tags and checking
  required extension members.
- Test Linux `.so` and Windows `.pyd` extension expectations for both native
  modules.
- Test cp311–cp314 support and rejection of excluded targets.
- Add an isolated core-import smoke test that scaffolds `env/`, `.env`,
  `pyproject.toml`, `etc/config.ini`, and `SITE_ROOT` as needed.
- Keep tests independent of database services and optional provider packages.

**NOT in scope**: CI matrix changes, PyPI publication, dependency metadata, or
runtime provider implementation changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_release_wheel.py` | CREATE | Pure archive/tag/extension validation helpers and tests. |
| `tests/test_windows_compatibility.py` | CREATE | Core import and Windows portability tests. |
| `tests/conftest.py` | MODIFY only if required | Temporary project/wheel fixtures. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing CI validation uses these standard-library modules:
import glob
import sys
import zipfile
```

```python
# Runtime modules under test:
import navigator
import navigator.types
import navigator.utils.types
```

### Existing Signatures to Use

```yaml
# .github/workflows/release.yml:82-94
required: ["navigator/types", "navigator/utils/types"]
wheels = glob.glob("wheelhouse/*.whl")
```

### Does NOT Exist

- ~~`tests/test_release_wheel.py`~~ — current workflow embeds validation inline.
- ~~`tests/test_windows_compatibility.py`~~ — no dedicated Windows smoke suite.
- ~~A fixture requiring an external database service~~ — this task must remain
  service-free.

## Implementation Notes

### Pattern to Follow

Follow asyncdb's archive-level validation at
`/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:37-55`, but
make platform suffix and tag assertions explicit as described in the spec.
Use the current post-publish environment setup at
`.github/workflows/release.yml:221-232` as the fixture contract.

### Key Constraints

- Synthetic wheel archives are sufficient for tag/member tests.
- Import tests must not silently depend on the developer's existing `env/`.
- Do not install uvloop or all optional extras merely to inspect a wheel.
- No test may claim macOS, win32, win_arm64, free-threaded, i686, musllinux,
  or PyPy support.

### References in Codebase

- `.github/workflows/release.yml:74-95,221-232`
- `navigator/types.pyx:1-56`
- `navigator/utils/types.pyx`
- `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:37-55`

## Acceptance Criteria

- [ ] Archive tests validate both required extensions for Linux and Windows.
- [ ] Windows checks require `win_amd64` and `.pyd`.
- [ ] Supported cp311–cp314 tags are covered; excluded tags are rejected.
- [ ] Core import smoke tests scaffold a temporary navconfig environment.
- [ ] Tests require no external service and do not install the full optional graph.
- [ ] Focused tests pass on the available local interpreter.

## Test Specification

```python
def test_linux_wheel_contains_cython_extensions(wheel_path):
    ...

def test_windows_wheel_contains_pyd_extensions(wheel_path):
    ...

def test_supported_wheel_tags(wheel_path):
    ...

def test_core_import_with_scaffolded_navconfig_environment():
    ...
```

## Agent Instructions

Verify TASK-2950 and TASK-2951 are complete. Keep validation helpers reusable by
the release workflow without importing project runtime dependencies into the
CI archive-only step.

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: 

**Deviations from spec**: none | describe if any
