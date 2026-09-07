# TASK-2953: Refactor release matrix and artifact publication

**Feature**: FEAT-007 — Navigator Wheel Build Infrastructure Refactor
**Spec**: `sdd/specs/wheel-build-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2950, TASK-2951, TASK-2952
**Assigned-to**: unassigned

---

## Context

Implement Module 4. The current workflow has only Ubuntu matrix entries,
uses cibuildwheel v2.21.3, installs unused Rust tooling, validates only Linux
`.so` members, publishes only manylinux wheels, and skips cp313 installation
tests under a stale dependency rationale. This task makes Linux/Windows
cp311–cp314 artifacts a blocking, publishable release contract.

## Scope

- Replace the Linux-only matrix with explicit Linux x86_64 and Windows AMD64
  cibuildwheel jobs for cp311, cp312, cp313, and cp314.
- Upgrade cibuildwheel/tool host configuration to finalized cp314 support.
- Skip win32, win_arm64, free-threaded, i686, musllinux, macOS, and PyPy.
- Remove Rust installation and Cargo path setup from the workflow.
- Add platform-aware archive/tag/extension validation as a blocking gate.
- Aggregate and publish manylinux and `win_amd64` wheels.
- Preserve sdist publication and trusted-publishing credentials.
- Update post-publish installation tests for Linux and Windows, with the
  narrowly documented cp314 upstream dependency exception if still necessary.
- Scaffold navconfig's required environment before runtime imports.

**NOT in scope**: Cython source edits, dependency metadata implementation,
new Rust tooling, macOS support, or PyPI credential changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | Build matrix, cibuildwheel, validation, aggregation, publication, smoke tests. |
| `tests/` | MODIFY only if needed | Integrate reusable validation from TASK-2952 without duplicating logic unnecessarily. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

The current inline validation uses only standard-library modules:

```python
import glob
import sys
import zipfile
```

The current post-publish smoke job imports:

```python
import navigator
import navigator.commands
from navigator.version import __version__
```

### Existing Signatures to Use

```yaml
# .github/workflows/release.yml:7-25
runs-on: ${{ matrix.os }}
matrix.include: Linux cp311/cp312/cp313 entries

# .github/workflows/release.yml:45-72
uses: pypa/cibuildwheel@v2.21.3
CIBW_BUILD: cp${{ matrix.pyver }}-*
CIBW_TEST_SKIP: "cp313-*"

# .github/workflows/release.yml:147-186
actions/download-artifact@v4
manylinux-only artifact movement and upload
```

### Does NOT Exist

- ~~Windows matrix entries~~ — none in current Navigator workflow.
- ~~`win_amd64` publication path~~ — deployment only moves/uploads manylinux.
- ~~Finalized cp314 build configuration~~ — current cibuildwheel version is too old.
- ~~A Rust consumer~~ — current rustup setup is dead configuration.

## Implementation Notes

### Pattern to Follow

Use `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:7-125`
for cross-platform matrix, archive checking, artifact aggregation, and
per-platform upload. Correct its cp314 limitation by using a supported host and
cibuildwheel version. Keep structural checks independent from dependency-heavy
installation tests.

### Key Constraints

- Archive validation must fail the job before upload.
- Linux checks require `.so`; Windows checks require `.pyd` and `win_amd64`.
- Do not make cp314 structural validation `continue-on-error`.
- Preserve sdist upload and existing PyPI secret names.
- Windows shell syntax must be valid on `windows-latest`; use cross-platform
  Python validation where possible.

### References in Codebase

- `.github/workflows/release.yml:7-102,131-246`
- `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:7-125`
- `/home/jesuslara/proyectos/navconfig/CHANGELOG.md:59-72`

## Acceptance Criteria

- [ ] Linux x86_64 and Windows AMD64 jobs request cp311–cp314.
- [ ] Finalized cp314 wheels are actually produced rather than silently skipped.
- [ ] Required wheel archive checks block publication on missing artifacts.
- [ ] Linux and Windows artifacts are aggregated and uploaded to PyPI.
- [ ] Rust installation and unused Cargo environment configuration are removed.
- [ ] Excluded platforms/ABIs are not built.
- [ ] Post-publish smoke tests scaffold navconfig's environment and cover both OS families.
- [ ] sdist publication remains functional.

## Test Specification

```python
def test_release_workflow_requests_supported_matrix():
    ...

def test_release_workflow_validates_platform_specific_extensions():
    ...

def test_release_workflow_publishes_manylinux_and_windows_artifacts():
    ...
```

## Agent Instructions

Verify TASK-2950 through TASK-2952 are complete. Validate YAML and embedded
Python scripts before considering the task complete. Do not run a real publish
from a development branch.

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: 

**Deviations from spec**: none | describe if any
