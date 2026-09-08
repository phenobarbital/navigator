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

- [x] Linux x86_64 and Windows AMD64 jobs request cp311–cp314.
- [x] Finalized cp314 wheels are actually produced rather than silently skipped.
- [x] Required wheel archive checks block publication on missing artifacts.
- [x] Linux and Windows artifacts are aggregated and uploaded to PyPI.
- [x] Rust installation and unused Cargo environment configuration are removed.
- [x] Excluded platforms/ABIs are not built.
- [x] Post-publish smoke tests scaffold navconfig's environment and cover both OS families.
- [x] sdist publication remains functional.

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

**Completed by**: sdd-worker (session_01ASHPx3ufe76XXQEpoGNxMM)
**Date**: 2026-09-08
**Notes**: Rewrote `.github/workflows/release.yml`'s `build` job matrix
with explicit Linux x86_64 (manylinux_2_28) and Windows AMD64 entries
for cp311-cp314 (8 total combinations), upgrading
`pypa/cibuildwheel` from `v2.21.3` to `v3.2.1` per the spec's External
Dependencies table. Removed the `rustup` install and
`CIBW_ENVIRONMENT: PATH=/root/.cargo/bin:$PATH` injection entirely.
`CIBW_SKIP` excludes win32/win_arm64/i686/musllinux/PyPy(`pp*`)/
free-threaded(`*t-*`) on both platforms; macOS was never in the matrix.
The archive-validation step ("Verify compiled extensions are present in
the wheel") now runs unconditionally (no `if:` guard) for every pyver
including cp314, and reuses `tests/test_release_wheel.py`'s helpers
(`wheel_archive_members`, `missing_required_extensions`,
`parse_wheel_tags`, `is_supported_linux_platform_tag`,
`is_supported_windows_platform_tag`) via `sys.path.insert(0, "tests")`
instead of duplicating tag-parsing logic, per TASK-2952's design intent.
`CIBW_TEST_SKIP` (the dependency-heavy install/import test inside
cibuildwheel) is narrowed from the stale `cp313-*` to `cp314-*` only,
since asyncdb/python-datamodel are the current cp314 gap. The `deploy`
job now aggregates and uploads both `*-manylinux*.whl` and
`*-win_amd64.whl` under the existing `NAVIGATOR_API_PYPI_API_TOKEN`
secret; sdist publication is unchanged. `test-installation` now runs a
`{ubuntu-latest, windows-latest} x {3.11..3.14}` matrix with
`continue-on-error` true only for `3.14` (structural validation in
`build` stays blocking regardless); its "Prepare navconfig project
environment" step scaffolds `env/dev/.env`, `.env`, `pyproject.toml`,
`etc/config.ini`, and `SITE_ROOT`/`ENV`, and "Test basic imports" now
explicitly imports `navigator.types`/`navigator.utils.types` (the
previous job only imported the top-level `navigator` package). All
`shell:`-bearing steps in that job use `bash` so the same script runs
on `windows-latest`. Added `tests/test_release_workflow.py`
implementing the task's three Test Specification functions plus one
extra covering the `test-installation` matrix, by parsing the workflow
YAML directly (`pyyaml`, already available transitively) — no network
access, no real publish triggered. Validated the YAML (`yaml.safe_load`)
and both embedded Python scripts (`compile()`) locally, and ran the
archive-validation heredoc end-to-end against a synthetic wheel. All 35
focused tests across TASK-2950/2951/2952/2953 pass.

**Deviations from spec**: Added `tests/test_release_workflow.py` beyond
the task's "Files to Create/Modify" table (which only listed
`.github/workflows/release.yml` and "tests/ MODIFY only if needed") to
satisfy the task's own Test Specification section, which named three
`test_release_workflow_*` functions with no other file able to host
them; kept strictly to static/offline validation, no other scope
change.
