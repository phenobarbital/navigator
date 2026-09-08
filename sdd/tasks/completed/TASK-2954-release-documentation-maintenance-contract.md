# TASK-2954: Document the supported wheel matrix and maintenance contract

**Feature**: FEAT-007 — Navigator Wheel Build Infrastructure Refactor
**Spec**: `sdd/specs/wheel-build-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2950, TASK-2951, TASK-2952, TASK-2953
**Assigned-to**: unassigned

---

## Context

Implement Module 5. Once the build and release behavior is changed, users and
maintainers need a clear distinction between Navigator's published wheel
support and optional provider support. The documentation should also make the
Cython-only boundary and excluded platforms explicit.

## Scope

- Document Linux x86_64 manylinux and Windows `win_amd64` wheel support for
  CPython 3.11–3.14.
- Document that macOS, win32, win_arm64, free-threaded, i686, musllinux, and
  PyPy wheels are outside the current release contract.
- Explain that optional integrations may have separate Windows/cp314 limits.
- Document that Cython extensions are part of the wheel contract and Rust is not
  currently shipped.
- Record the navconfig environment requirement for import smoke tests in the
  appropriate maintainer-facing release documentation.
- Update the changelog with the release-infrastructure change if the project
  convention requires it.

**NOT in scope**: workflow implementation, dependency metadata, runtime API
changes, or new Rust tooling.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `README.md` | MODIFY if selected by project convention | User-facing platform and wheel support. |
| `CHANGELOG.md` | MODIFY if selected by project convention | Release note for Python 3.14/Windows wheel infrastructure. |
| `docs/` release documentation | MODIFY only if selected | Maintainer smoke-test/build notes. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new runtime imports are required.

### Existing Signatures to Use

```text
# navconfig README.md:397-404
Python 3.14 is supported; Cython extensions require Cython >= 3.1.4;
Windows skips uvloop and preserves the existing asyncio policy.

# navconfig CHANGELOG.md:59-72
Python 3.13 and 3.14 are built in its release wheel matrix.
```

### Does NOT Exist

- ~~Navigator documentation promising Windows wheels~~ — no current promise
  exists to update; this task creates the explicit contract.
- ~~Navigator macOS wheel support~~ — explicitly excluded by the spec.
- ~~Navigator Rust extension documentation~~ — no Rust extension is shipped.

## Implementation Notes

### Pattern to Follow

Use the sibling package wording as a model, but document Navigator's narrower
Linux/Windows scope rather than copying asyncdb's macOS matrix.

### Key Constraints

- Documentation must not promise all optional database providers on Windows.
- Keep version/platform claims synchronized with TASK-2953's actual matrix.
- Avoid documenting unpublished or experimental artifacts as supported.

### References in Codebase

- `README.md`
- `CHANGELOG.md`
- `sdd/specs/wheel-build-refactor.spec.md:245-273`
- `/home/jesuslara/proyectos/navconfig/README.md:397-404`
- `/home/jesuslara/proyectos/navconfig/CHANGELOG.md:59-72`

## Acceptance Criteria

- [x] Supported Python/platform wheel matrix is documented accurately.
- [x] Excluded platforms and optional-provider limitations are explicit.
- [x] Cython-only/native extension contract is documented.
- [x] Changelog/release notes follow repository convention.
- [x] Documentation contains no stale cp313-only or macOS claims.

## Test Specification

```python
def test_documented_wheel_matrix_matches_release_contract():
    ...
```

## Agent Instructions

Verify TASK-2950 through TASK-2953 are complete. Read the selected documentation
files before editing and keep the change limited to release support claims.

## Completion Note

**Completed by**: sdd-worker (session_01ASHPx3ufe76XXQEpoGNxMM)
**Date**: 2026-09-08
**Notes**: Added a "🖥️ Platform & Wheel Support" section to `README.md`
documenting the `manylinux_2_28_x86_64` / `win_amd64` wheel matrix for
CPython 3.11-3.14, explicitly listing macOS/`win32`/`win_arm64`/
free-threaded/`i686`/`musllinux`/PyPy as not built or published, the
Cython-only (no Rust/PyO3/maturin) build contract, and that optional
integrations (uvloop, individual providers) may have narrower Windows/
cp314 support than the core package. Added a "🧑‍🔧 Building From
Source (Maintainers)" section recording the navconfig project-
scaffolding requirement (`env/<ENV>/.env`, `.env`, `pyproject.toml`,
`etc/config.ini`, `SITE_ROOT`) needed to exercise the compiled
extensions against real configuration, referencing
`tests/test_release_wheel.py`'s fixture and the release workflow.
Recorded the release-infrastructure change in `CHANGELOG.md`'s
`[Unreleased]` section under new `### Added`/`### Fixed` headings plus
an addition to the existing `### Changed` heading, following the
repository's Keep a Changelog convention. Added
`tests/test_release_documentation.py` implementing
`test_documented_wheel_matrix_matches_release_contract`, which parses
`.github/workflows/release.yml`'s actual build matrix (via `pyyaml`)
and cross-checks it against the README's documented claims, so the
docs cannot silently drift from the release matrix implemented in
TASK-2953. All 36 focused tests across TASK-2950-2954 pass.

**Deviations from spec**: none — `docs/` exists (Sphinx API docs,
`docs/sdd/`, `docs/ops/`) but has no existing release/wheel-support
documentation path, so `README.md`/`CHANGELOG.md` were selected as the
user/maintainer-facing documentation per the task's "MODIFY if selected
by project convention" instruction.
