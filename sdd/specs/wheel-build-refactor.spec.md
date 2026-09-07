---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
reuse_feature_id: FEAT-007
---

# Feature Specification: Navigator Wheel Build Infrastructure Refactor

**Feature ID**: FEAT-007
**Date**: 2026-09-08
**Author**: Jesus Lara / Codex
**Status**: draft
**Target version**: TBD

> `FEAT-007` is intentionally reused from the existing `wheel-build-refactor`
> proposal and research state. The repository allocator could not run because
> `sdd/tasks/.id_ledger.json` is absent, and allocating a second ID would fork
> an already-owned feature identity.

## 1. Motivation & Business Requirements

### Problem Statement

Navigator's release pipeline is not a reliable cross-platform wheel pipeline.
The current workflow builds Linux wheels only for CPython 3.11–3.13, validates
only Linux `.so` extensions, and publishes only manylinux artifacts. The linked
failure was ultimately caused by the post-build smoke test importing
`navigator.types` in an empty temporary directory: an unused import from
`navconfig` triggered runtime environment discovery and raised
`FileExistsError`. The wheel compilation and auditwheel repair themselves
succeeded.

Navigator also needs Python 3.14 and Windows `win_amd64` wheels. The owner has
recently made `asyncdb` and `navconfig`—two core first-party packages—work with
Python 3.14 and Windows, providing proven packaging and dependency-boundary
precedents for this refactor.

### Goals

- Build and publish Navigator wheels for CPython 3.11, 3.12, 3.13, and 3.14.
- Target Linux x86_64 manylinux wheels and Windows AMD64 (`win_amd64`) wheels.
- Preserve and validate both Navigator Cython extensions on every wheel:
  `navigator.types` and `navigator.utils.types`.
- Remove build-time coupling to `navconfig` where it is not required by the
  extension build, while preserving legitimate runtime use through
  `navigator/conf.py` and other modules.
- Prevent the `asyncdb` uvloop extra from making Windows installation fail.
- Replace the current environment-sensitive inline smoke test with a
  cross-platform smoke path that creates the required navconfig project
  environment before importing Navigator.
- Make structural wheel validation a blocking release gate for every target.
- Keep the pipeline Cython-only; do not add Rust, PyO3, maturin, or Rust source
  files to Navigator in this feature.

### Non-Goals (explicitly out of scope)

- macOS wheel production or publication. It may be reconsidered later as an
  additive matrix change.
- New Rust/PyO3 extensions, maturin integration, or `setuptools-rust` setup.
- Changes to Navigator runtime APIs or application behavior unrelated to import
  and dependency portability.
- Guaranteeing that every optional integration provider is usable on Windows.
- Changing PyPI credentials, release environments, or trusted-publishing policy.

## 2. Architectural Design

### Overview

Use one explicit, data-driven cibuildwheel release contract for Linux x86_64
and Windows AMD64 across CPython 3.11–3.14. Keep setuptools as the build
backend and `setup.py` as the Cython extension boundary. Align build-system
requirements with what `setup.py` actually imports, remove the unused
`navconfig` import from `navigator/types.pyx`, and make the uvloop dependency
platform-safe. Validate wheel filenames and archive contents before artifact
publication, then run an isolated import smoke test that scaffolds the
navconfig-required project environment.

The design follows the two first-party precedents with different roles:

- `navconfig` is the closer compatibility precedent: Python 3.14 metadata,
  Cython `>=3.1.4`, Linux/Windows wheels, and a Windows-safe uvloop marker.
- `asyncdb` is the archive-validation and multi-platform cibuildwheel
  precedent, but its current host/tool version does not actually produce cp314
  wheels; Navigator must use a cibuildwheel version and host Python that do.

### Component Diagram

```text
pyproject.toml + setup.py
          │
          ▼
   Cython extensions ──► cibuildwheel matrix
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          Linux manylinux              Windows win_amd64
                 │                         │
                 └────────────┬────────────┘
                              ▼
                archive/tag/extension gate
                              │
                              ▼
             scaffolded import smoke + publish
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `pyproject.toml` | modifies | Remove unused build-time `navconfig[default]`; add Python 3.14 metadata; make uvloop dependency markers Windows-safe. |
| `setup.py` | preserves/clarifies | Continue compiling the two Cython extensions with setuptools. |
| `navigator/types.pyx` | modifies | Remove unused `from navconfig import config, DEBUG` import that triggers bootstrap during isolated wheel tests. |
| `navigator/__init__.py` | preserves contract | Continue tolerating absent/incompatible uvloop and runtime navconfig initialization failures where already guarded. |
| `.github/workflows/release.yml` | replaces release orchestration | Add Linux/Windows cp311–cp314 matrix, upgrade cibuildwheel, remove dead rustup setup, validate and publish both platform families. |
| `navigator/commands/env.py` / `kardex env create` behavior | used by smoke test | Scaffold the `env/` project state required by navconfig before importing runtime modules. |
| `asyncdb` release workflow | follows pattern | Reuse archive-level `.so`/`.pyd` checking and artifact aggregation concepts. |
| `navconfig` metadata and release setup | follows pattern | Reuse Python 3.14 Cython requirements and `sys_platform != 'win32'` uvloop boundary. |

### Data Models

No new runtime data model is required. The release matrix and required native
module list are CI configuration data. The validation helper may represent a
wheel as a path plus parsed PEP 427 tags, but that is test/build tooling only.

### New Public Interfaces

None. This feature changes package metadata, build configuration, and release
verification; it does not add a Navigator runtime API.

## 3. Module Breakdown

### Module 1: Packaging Metadata and Dependency Boundaries

- **Path**: `pyproject.toml`, `setup.cfg`, `MANIFEST.in`
- **Responsibility**: Make build requirements, Python classifiers, package
  discovery, wheel tags, and platform-specific dependencies coherent.
- **Depends on**: Module 2's extension inventory and Module 4's compatibility
  matrix.
- **Required changes**:
  - Remove `navconfig[default]` from `[build-system].requires`; retain
    navconfig as a runtime dependency where Navigator imports it at runtime.
  - Add the Python 3.14 classifier.
  - Remove or correct legacy `[wheel]` declarations that advertise
    `python-tag = py310` and `universal = 1` for compiled extensions.
  - Remove `uvloop` from the unconditional `asyncdb[uvloop,default,boto3]`
    dependency path and expose it only through a Windows-excluded optional
    dependency marker.
  - Preserve explicit package discovery and native source inclusion.

### Module 2: Cython Extension Import Boundary

- **Path**: `setup.py`, `navigator/types.pyx`
- **Responsibility**: Keep the Cython build self-contained and prevent dead
  runtime configuration imports from breaking isolated wheel tests.
- **Depends on**: Module 1.
- **Required changes**:
  - Preserve the `navigator.utils.types` C extension and `navigator.types` C++
    extension declarations.
  - Remove the unused `navconfig` import from `navigator/types.pyx`.
  - Do not add Rust or maturin build hooks.

### Module 3: Wheel Validation and Portability Tests

- **Path**: `tests/test_release_wheel.py`, `tests/test_windows_compatibility.py`
  or the repository's selected focused-test paths
- **Responsibility**: Test wheel tags, required archive contents, platform
  suffixes, and core import behavior without external services.
- **Depends on**: Modules 1, 2, and 4.
- **Required coverage**:
  - Linux wheels contain `navigator/types.*.so` and
    `navigator/utils/types.*.so`.
  - Windows wheels contain `navigator/types.*.pyd` and
    `navigator/utils/types.*.pyd` and have `win_amd64` tags.
  - Supported wheel tags cover cp311, cp312, cp313, and cp314; free-threaded,
    win32, win_arm64, i686, musllinux, and macOS artifacts are not requested.
  - The smoke test creates the required project environment before importing
    `navigator`, `navigator.types`, and `navigator.utils.types`.
  - Missing optional dependencies do not prevent core wheel validation.

### Module 4: Release Matrix and Artifact Publication

- **Path**: `.github/workflows/release.yml`
- **Responsibility**: Build, validate, aggregate, publish, and post-publish test
  the Linux and Windows wheel matrix.
- **Depends on**: Modules 1–3.
- **Required behavior**:
  - Use a cibuildwheel version with finalized cp314 support and a supported
    host Python (not the asyncdb cp314-skipping host/tool combination).
  - Build Linux x86_64 manylinux and Windows AMD64 wheels for cp311–cp314.
  - Skip win32, win_arm64, free-threaded, i686, musllinux, and macOS targets.
  - Remove the unused Rust toolchain installation and `/root/.cargo/bin` path
    injection.
  - Make archive validation blocking before upload.
  - Aggregate and publish both `*-manylinux*` and `*-win_amd64*` wheels.
  - Keep source distribution publication.
  - Run post-publish installation/import tests on Linux and Windows for cp311–
    cp314. The cp314 install test may remain `continue-on-error` only while
    upstream `asyncdb` and `python-datamodel` do not publish cp314 wheels;
    structural validation must remain blocking.

### Module 5: Release Documentation and Maintenance Contract

- **Path**: `README.md`, `CHANGELOG.md` or the repository's selected release
  documentation path
- **Responsibility**: Document the supported wheel matrix and distinguish
  package build support from optional provider support on Windows.
- **Depends on**: Modules 1–4.

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_linux_wheel_contains_cython_extensions` | Module 3 | Synthetic/archive check confirms both required `.so` extensions are present. |
| `test_windows_wheel_contains_pyd_extensions` | Module 3 | Confirms both required `.pyd` extensions and the `win_amd64` platform tag. |
| `test_supported_wheel_tags` | Module 3 | Accepts cp311–cp314 platform wheels and rejects excluded ABI/platform tags. |
| `test_core_import_with_scaffolded_navconfig_environment` | Module 3 | Imports the compiled modules after creating the required `env/`/`SITE_ROOT` project context. |
| `test_core_import_does_not_require_uvloop_on_windows` | Module 3 | Confirms the core import path remains usable without uvloop on Windows. |
| `test_build_metadata_has_no_stale_universal_tag` | Module 1 | Verifies compiled-wheel metadata is not declared universal or hard-coded to py310. |
| `test_build_metadata_does_not_require_navconfig_for_cython_build` | Module 1 | Confirms isolated build requirements contain only actual build inputs. |

### Integration Tests

| Test | Description |
|---|---|
| `test_cibuildwheel_linux_matrix` | CI produces and validates cp311–cp314 manylinux x86_64 wheels. |
| `test_cibuildwheel_windows_matrix` | CI produces and validates cp311–cp314 `win_amd64` wheels. |
| `test_published_linux_install` | Installs each published Linux wheel and runs the scaffolded core import smoke test. |
| `test_published_windows_install` | Installs each published Windows wheel and runs the scaffolded core import smoke test without uvloop. |
| `test_source_distribution_build` | Builds the sdist and confirms it contains the Cython source needed for a fallback build. |

### Test Data / Fixtures

- Synthetic wheel archives containing representative `.so` and `.pyd` names for
  platform-independent validation tests.
- A temporary project root with the same required markers as the existing
  post-publish smoke job: `env/`, `.env`, `pyproject.toml`, `etc/config.ini`,
  and `SITE_ROOT`.
- No database, Redis, Cassandra, Windows service, or other external service.

## 5. Acceptance Criteria

- [ ] `navigator-api` builds wheels for CPython cp311, cp312, cp313, and cp314.
- [ ] Linux output targets manylinux x86_64 and Windows output targets only
      `win_amd64`.
- [ ] Every published wheel contains compiled `navigator.types` and
      `navigator.utils.types` extensions with `.so` on Linux and `.pyd` on
      Windows.
- [ ] The release workflow fails before publication if any expected wheel or
      required extension is missing.
- [ ] The release workflow no longer installs Rust or depends on a Rust/Cargo
      project.
- [ ] The release workflow uses a cibuildwheel version/tooling combination that
      actually builds finalized CPython 3.14 wheels.
- [ ] The unused `navconfig` import is removed from `navigator/types.pyx`, and
      the isolated cibuildwheel smoke test no longer fails with the missing
      `env/` `FileExistsError`.
- [ ] `navconfig` is not required in the isolated Cython build environment, but
      remains available for legitimate Navigator runtime imports.
- [ ] `asyncdb`'s uvloop extra cannot force a Windows installation to resolve
      uvloop; Linux production behavior remains available through the guarded
      optional dependency.
- [ ] The smoke test scaffolds the required navconfig environment before
      importing runtime modules.
- [ ] macOS, win32, win_arm64, free-threaded, i686, musllinux, and PyPy wheels
      are not built or published by this feature.
- [ ] The source distribution still builds and publishes.
- [ ] Focused packaging and portability tests pass on the supported local
      interpreter; CI matrix validation passes on Linux and Windows.
- [ ] No Navigator public runtime API changes are introduced.

## 6. Codebase Contract

> This contract is grounded in the finalized `wheel-build-refactor` brainstorm
> and re-verified against the current `dev` branch. Implementation agents must
> re-check any line that changes before applying a task.

### Verified Imports

```python
# navigator/types.pyx:4-8
from typing import Tuple, Callable, Awaitable
from urllib.parse import urlparse, parse_qs, ParseResult
from aiohttp import web
from navconfig import config, DEBUG
from .exceptions.exceptions import ValidationError
```

The `navconfig` import above is the known dead import to remove; `config` and
`DEBUG` are not referenced elsewhere in `navigator/types.pyx`. Runtime imports
of navconfig elsewhere remain legitimate, especially `navigator/conf.py:8`.

### Existing Class Signatures

No runtime class or method signature is extended by this feature. The native
extension declarations are the relevant build contract:

```python
# setup.py:29-42
Extension(
    name="navigator.utils.types",
    sources=["navigator/utils/types.pyx"],
    language="c",
)
Extension(
    name="navigator.types",
    sources=["navigator/types.pyx"],
    language="c++",
)
```

### Integration Points

| New/Changed Component | Connects To | Via | Verified At |
|---|---|---|---|
| Cython build metadata | setuptools build backend | `[build-system]` and `setup()` | `pyproject.toml:1-9`, `setup.py:44-56` |
| Cython extensions | wheel archive | extension filenames | `setup.py:29-42` |
| Linux/Windows CI matrix | cibuildwheel | `CIBW_BUILD`, runner, architecture variables | `.github/workflows/release.yml:7-57` |
| Archive validation | generated wheels | `zipfile` member inspection | `.github/workflows/release.yml:74-95` |
| Runtime smoke test | navconfig environment | `SITE_ROOT`, `env/`, `etc/config.ini` | `.github/workflows/release.yml:221-232` |
| Windows optional dependency boundary | uvloop | optional dependency marker | `/home/jesuslara/proyectos/navconfig/pyproject.toml:73-76` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator/Cargo.toml`~~ — no tracked Cargo manifest exists.
- ~~Navigator PyO3/maturin module~~ — no tracked Rust source or maturin
  configuration exists.
- ~~Navigator Windows release job~~ — current workflow has only Ubuntu entries.
- ~~A reusable wheel-validation test module~~ — the current workflow embeds
  its archive check; the focused test module is part of this feature.
- ~~cp314 Navigator wheels~~ — current published Navigator artifacts stop at
  cp313.

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `asyncdb/.github/workflows/release.yml:7-61` for cibuildwheel matrix,
  Windows AMD64 selection, and archive-level Cython extension checks, while
  correcting its cp314 host/tool limitation.
- Follow `navconfig/pyproject.toml:1-7,20-30,73-90` for Python 3.14 Cython
  build requirements and the Windows-safe uvloop marker.
- Keep setuptools as the backend. Do not introduce maturin or Rust tooling.
- Keep structural wheel validation independent from dependency-heavy imports;
  use the scaffolded smoke test only for the runtime import contract.
- Keep the release matrix data-driven so macOS can be reconsidered later
  without changing validation architecture.

### Known Risks / Gotchas

- `navconfig` is a legitimate runtime dependency but must not be installed only
  to compile Cython extensions. Removing it from build requirements must not
  remove it from runtime dependency metadata.
- `asyncdb[uvloop,default,boto3]` currently pulls a uvloop version without
  Windows wheels. The dependency change must preserve Linux production support
  while preventing Windows resolution failure.
- The current cp313 test skip was introduced for an old cassandra-driver gap;
  after dependency updates, the skip must be removed or narrowed rather than
  copied forward.
- CPython 3.14 support requires a cibuildwheel release and host Python that
  recognize finalized cp314 targets; merely adding `cp314-*` to an old selector
  is insufficient.
- Runtime smoke imports must create the navconfig project environment before
  importing modules that legitimately access configuration.
- Keep source distributions usable for dependencies that do not yet publish
  cp314 wheels; this does not weaken Navigator's own wheel-content gate.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `setuptools` | existing `>=67.6.1`; align with sibling proven version as needed | Build backend and extension compilation. |
| `Cython` | existing `>=3.0.11,<4`; evaluate `>=3.1.4` alignment | Generate Cython extension sources compatible with Python 3.14. |
| `wheel` | existing `>=0.44.0` | Wheel packaging. |
| `setuptools-scm` | existing `>=6.0` | Version generation from repository metadata. |
| `cibuildwheel` | upgrade from `v2.21.3` to a finalized cp314-capable `v3.2.1+`/current approved `v4.x` | Cross-platform wheel builds for Linux and Windows. |
| `pytest` | existing test extra | Focused packaging and smoke tests. |

No Rust, maturin, PyO3, or `setuptools-rust` dependency is introduced.

### Worktree Strategy

- **Recommended isolation**: mixed.
- Packaging metadata and focused validation tests can be developed independently
  after the wheel contract is fixed.
- Workflow changes depend on the exact artifact names and validation helper
  contract, so CI integration follows those tasks.
- The feature touches `pyproject.toml`, `setup.py`, `setup.cfg`,
  `navigator/types.pyx`, `.github/workflows/release.yml`, and focused tests;
  runtime feature work should not be mixed into the same task.

## 8. Open Questions

All brainstorm questions were resolved by the maintainer and are carried here:

- [x] **Failure class** — *Owner: maintainer*: post-build test-harness/import-time coupling caused by the unused navconfig import in `navigator/types.pyx`; compilation and auditwheel repair succeeded.
- [x] **Runtime environment** — *Owner: maintainer*: `env/` is required by navconfig at runtime; smoke tests must scaffold it, but navconfig is not a Cython build requirement.
- [x] **Published platforms** — *Owner: maintainer*: Linux x86_64 and Windows AMD64 only; macOS is dropped from this feature.
- [x] **Windows matrix** — *Owner: maintainer*: `win_amd64`, CPython cp311–cp314; skip win32, win_arm64, free-threaded, i686, musllinux, macOS, and PyPy.
- [x] **Rust scope** — *Owner: maintainer*: no Rust extensions are planned; this refactor is Cython-only.
- [x] **First-party precedents** — *Owner: maintainer*: asyncdb and navconfig are valid sibling references, with navconfig the closer Python 3.14/Windows precedent and asyncdb the archive-validation precedent.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-08 | Jesus Lara / Codex | Initial formal specification from finalized brainstorm and verified build evidence. |
