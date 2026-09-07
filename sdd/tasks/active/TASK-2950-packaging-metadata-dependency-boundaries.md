# TASK-2950: Align packaging metadata and dependency boundaries

**Feature**: FEAT-007 — Navigator Wheel Build Infrastructure Refactor
**Spec**: `sdd/specs/wheel-build-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement Module 1 of the spec. Navigator's build metadata still installs
`navconfig[default]` in the isolated build environment, declares no Python 3.14
classifier, advertises `py310`/`universal` in `setup.cfg`, and pulls
`asyncdb[uvloop,...]` into the base dependency path. These declarations must
describe the actual Cython build and remain installable on Windows.

## Scope

- Remove `navconfig[default]` from `[build-system].requires` while retaining
  navconfig as a runtime dependency where required.
- Add the Python 3.14 classifier and align Cython/build requirements with the
  finalized compatibility contract.
- Remove or correct the stale universal/py310 wheel declarations.
- Remove uvloop from the unconditional asyncdb extra path and expose uvloop
  only through a Windows-excluded optional dependency marker.
- Preserve explicit package discovery and native source inclusion.
- Add focused metadata tests if the repository's selected test structure needs
  them.

**NOT in scope**: Cython source edits, release workflow changes, Rust tooling,
or broad runtime dependency cleanup.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Build requirements, Python 3.14 metadata, and platform-safe dependencies. |
| `setup.cfg` | MODIFY or DELETE | Remove stale universal/py310 wheel metadata. |
| `MANIFEST.in` | MODIFY only if required | Preserve Cython source inclusion without unrelated manifest changes. |
| `tests/` focused metadata test path | CREATE or MODIFY | Verify metadata contract. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new runtime imports are required. Build metadata is consumed by setuptools.

### Existing Signatures to Use

```toml
# pyproject.toml:1-9
[build-system]
build-backend = "setuptools.build_meta"

# pyproject.toml:51, 64-65, 92-101
requires-python = ">=3.11"
dependencies = ["asyncdb[uvloop,default,boto3]>=2.13.1", "navconfig[default]>=2.1.3"]
uvloop = ["uvloop>=0.21.0"]

# setup.cfg:1-4
[wheel]
python-tag = py310
universal = 1
```

### Does NOT Exist

- ~~Navigator's Python 3.14 classifier~~ — absent from `pyproject.toml:31-50`.
- ~~A separate Windows-safe asyncdb dependency declaration~~ — the current
  base dependency includes the uvloop extra unconditionally.
- ~~A Rust/Cargo build dependency~~ — none is required or present for this
  feature.

## Implementation Notes

### Pattern to Follow

Follow `/home/jesuslara/proyectos/navconfig/pyproject.toml:1-7,20-30,73-90`
for Python 3.14 metadata, Cython build requirements, and the
`sys_platform != 'win32'` uvloop marker. Keep Navigator's explicit package
discovery at `pyproject.toml:207-221`.

### Key Constraints

- Do not remove navconfig from legitimate runtime dependencies.
- Do not claim macOS, win32, win_arm64, free-threaded, or PyPy wheel support.
- Do not introduce maturin, PyO3, or setuptools-rust.
- Metadata tests must not require network access or external services.

### References in Codebase

- `pyproject.toml:1-9,31-51,55-81,84-101,161-168,207-221`
- `setup.cfg:1-4`
- `MANIFEST.in:1-45`
- `/home/jesuslara/proyectos/navconfig/pyproject.toml:1-7,20-30,73-90`

## Acceptance Criteria

- [ ] Build-system requirements no longer include `navconfig[default]`.
- [ ] Python 3.14 is advertised and build requirements support it.
- [ ] No universal or hard-coded `py310` wheel metadata remains for compiled wheels.
- [ ] Windows installation does not resolve uvloop through Navigator's base asyncdb dependency.
- [ ] Linux production installations retain an explicit optional uvloop path.
- [ ] Existing package discovery and Cython source inclusion remain intact.
- [ ] Focused metadata tests pass.

## Test Specification

```python
def test_build_metadata_has_python_314_and_no_universal_wheel_tag():
    ...

def test_build_system_does_not_require_navconfig_runtime_extra():
    ...

def test_uvloop_dependency_excludes_windows():
    ...
```

## Agent Instructions

Read the spec, verify the metadata locations above, implement only this task,
run focused tests, and leave the task pending until the executor completes it.

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: 

**Deviations from spec**: none | describe if any
