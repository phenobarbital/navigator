---
type: feature
base_branch: dev
---

# Brainstorm: Navigator wheel-build refactor

**Date**: 2026-09-08
**Author**: Codex
**Status**: questions-resolved
**Recommended Option**: A

## Problem Statement

Navigator's release workflow currently builds only Linux wheels for CPython
3.11–3.13, validates Linux-native extensions, and publishes only manylinux
artifacts. Navigator itself contains Cython extensions, while the requested
future direction also mentions mixed Cython/Rust builds. The problem is now
better bounded by two first-party sibling packages: the owner has recently
fixed both `asyncdb` and `navconfig` for Python 3.14 and Windows compatibility.
Those repositories provide proven local patterns rather than hypothetical
examples.

## Q&A Context

### Round 1 — intent and success

- **Intent**: make Navigator's package build infrastructure reliable and align
  it with the working native-package release patterns already used in
  `asyncdb` and `navconfig`.
- **Users**: Navigator consumers installing wheels on supported CPython and
  Windows environments, plus maintainers publishing releases.
- **Success**: reproducible wheels for the agreed CPython/platform matrix;
  compiled Cython extensions present with correct platform suffixes; archive
  and installation smoke checks fail before publication when artifacts are
  incomplete.

### Round 2 — new evidence and boundaries

- **Owner-provided answer**: `asyncdb` and `navconfig` are owned by the same
  maintainer and were recently fixed to build for Python 3.14 and support
  Windows.
- **Consequence**: the design should reuse and consolidate their proven
  packaging/CI conventions where compatible, and compare their differences
  before introducing a new Rust/maturin build path.
- **Boundary**: this brainstorm does not assume that Navigator must add Rust
  immediately; Navigator currently has Cython source but no tracked Cargo or
  PyO3 module.

### Round 3 — open questions resolved with evidence (2026-09-08)

Evidence lives in `sdd/state/FEAT-007/findings/F008–F010.md` (Actions job logs
fetched with `gh api`, PyPI file lists, and the asyncdb/navconfig trees).

- **Actions failure**: the wheel compiled and `auditwheel` repaired it; the job
  died in cibuildwheel's post-build import test. `navigator/types.pyx:7` runs
  `from navconfig import config, DEBUG` at module load, navconfig's lazy
  `bootstrap()` requires an `env/` directory, and the test runs in an empty
  temp dir. Neither name is used in `types.pyx`, so the import is dead code.
  cp313 passed only because `CIBW_TEST_SKIP: cp313-*` skipped the test.
- **Correction to Round 2**: asyncdb requests cp314 but publishes no cp314
  wheels. Its release pins host Python 3.10, which resolves to cibuildwheel
  2.23.4, where cp314 is a prerelease target skipped by
  `CIBW_PRERELEASE_PYTHONS: "0"`. navconfig 2.5.1 (2026-09-07) does publish
  cp310–cp314 for manylinux and `win_amd64`. python-datamodel publishes
  neither cp314 nor macOS wheels.
- **Windows install blocker**: Navigator's base dependencies request
  `asyncdb[uvloop,default,boto3]`; asyncdb pins `uvloop==0.21.0`, which has no
  Windows wheels. `uvloop` must leave the base extras and be guarded with
  `sys_platform != 'win32'`, as navconfig 2.5.1 does.
- **Tooling**: `pypa/cibuildwheel@v2.21.3` predates cp314 (default cp314
  builds since 3.1.0, CPython 3.14.0 final since 3.2.1, latest 4.2.1). The
  rustup install in `CIBW_BEFORE_BUILD` is consumed by nothing.
  `[build-system].requires` lists `navconfig[default]` although `setup.py`
  never imports it.

## Constraints & Requirements

- Preserve Navigator's existing Cython extension behavior while supporting
  platform-specific `.so` and `.pyd` artifacts.
- Add Python 3.14 to the release contract and retain the currently supported
  Python versions unless an explicit compatibility decision changes them.
- Add Windows wheel production and validation; define architecture/ABI scope
  explicitly before implementation.
- Keep artifact validation independent from installing the full optional
  dependency graph, because dependency availability can be a separate failure
  from wheel compilation.
- Treat `asyncdb` and `navconfig` as first-party references and verify their
  current build requirements before copying patterns.
- Do not add Rust/maturin solely because the request mentions future mixed
  native code; introduce it only if Navigator has a concrete Rust extension
  to build.
- Keep runtime APIs and application behavior out of scope unless packaging
  research proves a dependency boundary blocks Windows installation.

## Options Explored

### Option A: Consolidate the proven sibling-package wheel contract

Refactor Navigator around the conventions already demonstrated by `asyncdb`
and `navconfig`: explicit build-system requirements, a cibuildwheel matrix for
the agreed CPython/platform set, archive-level extension checks, and separate
platform publication. Add a small shared conceptual contract for future native
components without introducing Rust tooling until a Rust source module exists.

✅ **Pros:**

- Lowest architectural risk because both sibling packages already exercise
  Python 3.14 and Windows requirements.
- Keeps the existing setuptools/Cython model understandable.
- Makes failures distinguishable: compilation, wheel contents, install smoke,
  and publication each have a clear boundary.
- Provides a direct migration path for a future Rust extension.

❌ **Cons:**

- Some workflow and validation logic may be duplicated across repositories
  until a shared action or reusable workflow is justified.
- Requires reconciling differences between Navigator's dependency graph and the
  simpler sibling-package build inputs.

📊 **Effort:** Medium

📦 **Libraries / Tools:**

| Package | Purpose | Notes |
|---|---|---|
| `setuptools` | Build backend and Cython extension packaging | Already used by Navigator, asyncdb, and navconfig. |
| `Cython` | Generate Navigator extension sources | Navigator currently requires it in `setup.py`/`pyproject.toml`. |
| `cibuildwheel` | Produce platform/interpreter wheels | Proven in asyncdb's release workflow. |
| `twine` or existing trusted publisher flow | Publish aggregated artifacts | Preserve Navigator's current release credentials/policy. |

🔗 **Existing Code to Reuse:**

- `asyncdb/.github/workflows/release.yml:7-61` — cross-platform cibuildwheel matrix, CPython 3.10–3.14, Windows AMD64, and archive checks.
- `asyncdb/.github/workflows/release.yml:63-125` — per-platform artifact detection and publication.
- `navconfig/pyproject.toml:1-7,20-30,73-90` — Python 3.14 metadata, Cython build requirements, and Windows-safe uvloop extra marker.
- `navconfig/setup.py:8-73` — Cython-only setup boundary with C and C++ extensions.
- `navigator/setup.py:9-56` — existing Navigator extension declarations to preserve or normalize.

### Option B: Adopt a unified mixed-backend build with maturin/PyO3

Make Rust/PyO3 or maturin a first-class build participant now, even if the
initial Rust component is small or a placeholder. Cython and Rust artifacts
would be produced through one documented native-build contract.

✅ **Pros:**

- Establishes the desired mixed-language infrastructure up front.
- Maturin provides strong Rust wheel conventions and platform tagging.
- Could reduce future migration work if a Rust component is imminent.

❌ **Cons:**

- No Navigator Rust source or Cargo manifest currently exists, so the design
  would solve an unverified need.
- Adds toolchain, caching, compiler, and failure modes to an already broken
  release path.
- May conflict with setuptools/Cython ownership of the existing extensions.

📊 **Effort:** High

📦 **Libraries / Tools:**

| Package | Purpose | Notes |
|---|---|---|
| `maturin` | Build and publish Rust-backed Python wheels | Introduce only with a concrete PyO3 module. |
| `PyO3` | Rust/Python extension boundary | Not present in the current Navigator source tree. |
| `setuptools`/`Cython` | Preserve existing Cython extensions | Still required for current native modules. |

🔗 **Existing Code to Reuse:**

- `navigator/setup.py:29-42` — current native extension inventory.
- `navigator/pyproject.toml:1-9,207-221` — current build backend and package discovery.

### Option C: Move release building into a shared organization-level workflow

Create a reusable GitHub Actions workflow or dedicated build repository used by
Navigator, asyncdb, and navconfig. Each package supplies metadata and extension
validation inputs; the central workflow owns matrix construction, artifact
aggregation, and publication conventions.

✅ **Pros:**

- Reduces long-term drift between the three first-party packages.
- Encodes the recently proven Python 3.14/Windows practice once.
- Makes future native-language additions consistent across packages.

❌ **Cons:**

- Introduces cross-repository versioning and release coupling.
- Makes debugging a package failure require navigating reusable workflow inputs.
- Too broad if Navigator alone is the immediate release blocker.

📊 **Effort:** High

📦 **Libraries / Tools:**

| Package | Purpose | Notes |
|---|---|---|
| GitHub Actions reusable workflows | Share release orchestration | Requires a stable interface for package-specific checks. |
| `cibuildwheel` | Common wheel builder | Already proven by asyncdb. |

🔗 **Existing Code to Reuse:**

- `asyncdb/.github/workflows/release.yml:7-125` — initial workflow contract.
- `navconfig/CHANGELOG.md:59-72` — evidence of the recently stabilized Python 3.13/3.14 release matrix.

## Recommendation

**Option A** is recommended because it directly addresses Navigator's current
failure with the least new machinery and is grounded in two first-party
packages that already meet the newly stated Python 3.14 and Windows goals.
Option C is a useful follow-up after the three workflows converge; Option B
should be activated only when Navigator has an actual Rust extension to ship.
The tradeoff is accepting some short-term workflow duplication in exchange for
clear ownership and a smaller recovery surface.

## Feature Description

### User-Facing Behavior

Consumers should be able to install Navigator wheels for the agreed CPython
versions on Linux and Windows without falling back unexpectedly to a source
build. Each published wheel should carry a truthful platform/interpreter tag
and contain both required compiled Cython modules. Supported macOS behavior
must be explicitly retained or removed as a release-policy decision.

### Internal Behavior

The release pipeline should build a complete matrix with cibuildwheel, validate
wheel filenames and archive contents before upload, and run a lightweight
installation/import smoke test that does not require every optional integration.
The packaging metadata should have one authoritative compatibility story rather
than relying on conflicting legacy wheel settings. Native build inputs should
be extensible, but Rust-specific tooling should remain dormant until a concrete
Rust module is added.

### Edge Cases & Error Handling

- A missing `.so` or `.pyd` extension fails the build before publication.
- A missing Python-version/platform artifact fails the matrix rather than
  silently publishing a partial release.
- Optional dependencies unavailable on Windows must be separated from core
  wheel compilation and reported as installation/test failures with context.
- Python 3.13/3.14 dependency gaps must not disable structural wheel checks.
- Artifact aggregation must handle manylinux, Windows, and any retained macOS
  wheels without platform-specific shell assumptions.

## Capabilities

### New Capabilities

- `navigator-cross-platform-wheels`: build and publish the agreed CPython and
  Windows/Linux wheel matrix.
- `navigator-wheel-validation`: verify tags, compiled extension contents, and
  lightweight installation behavior before publication.
- `navigator-native-build-contract`: document extension points for Cython now
  and Rust/PyO3 later.

### Modified Capabilities

- Existing release workflow capability in `.github/workflows/release.yml`.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator/setup.py` | modifies | Normalize the existing C/C++ Cython extension build boundary. |
| `navigator/pyproject.toml` | modifies | Align build requirements, Python classifiers, and package metadata. |
| `navigator/setup.cfg` | modifies or removes | Resolve legacy wheel tag declarations. |
| `.github/workflows/release.yml` | modifies | Add explicit Python/platform matrix, validation, aggregation, and publication. |
| `tests/` | extends | Add pure archive/tag and core import smoke coverage. |
| `asyncdb` and `navconfig` | depends on patterns | First-party reference implementations; no runtime dependency change implied. |

## Code Context

### User-Provided Code

No code snippet was provided. The user-provided architectural context is:

> `asyncdb` and `navconfig` are two core packages owned by the maintainer and
> were recently fixed to build for Python 3.14 and added Windows compatibility
> support.

### Verified Codebase References

#### Classes & Signatures

No runtime classes or signatures are required for this packaging brainstorm.

#### Verified Imports

No new runtime imports are proposed.

#### Key Attributes & Constants

- Navigator extension `navigator.utils.types` is declared in `navigator/setup.py:30-35`.
- Navigator extension `navigator.types` is declared in `navigator/setup.py:36-41`.
- asyncdb requests `CIBW_BUILD` for `cp310` through `cp314` and `CIBW_ARCHS_WINDOWS=AMD64` in `asyncdb/.github/workflows/release.yml:26-33`.
- navconfig advertises Python 3.14 and requires Cython `>=3.1.4` in `navconfig/pyproject.toml:1-7,20-30,86-90`.

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator/Cargo.toml`~~ — no tracked Cargo manifest was found.
- ~~Navigator PyO3/maturin module~~ — no tracked Rust source or maturin configuration was found.
- ~~Windows build job in Navigator's current release workflow~~ — current Navigator workflow is Linux-only.

## Parallelism Assessment

- **Internal parallelism**: Moderate. Metadata cleanup, archive-validation tests,
  and CI matrix work can be developed separately, but they converge on the
  wheel naming and artifact contract.
- **Cross-feature independence**: Mostly independent of runtime features, but
  shares `pyproject.toml` and `.github/workflows/release.yml` with release
  maintenance.
- **Recommended isolation**: mixed.
- **Rationale**: Keep packaging metadata and test-contract work separable, then
  integrate the workflow changes after the artifact contract is agreed.

## Open Questions

All questions are resolved. Items marked *recommended* are evidence-backed
defaults the maintainer can flip before `/sdd-spec`.

- [x] What exact failure is reported by the linked Actions job? — *Owner: maintainer*: `FileExistsError: NavConfig could not find the expected environment directory` raised from navconfig's `BaseLoader.__init__` during `import navigator.types` inside cibuildwheel's test command (cp311 and cp312; cp313 skipped its test). Class: test-harness / import-time coupling, not compilation, dependency install, or publication. Fix: remove the unused `from navconfig import config, DEBUG` in `navigator/types.pyx`, make the archive-level `.so`/`.pyd` check the blocking gate, and run the import smoke test from a Python script that scaffolds `env/<env>/.env` and `SITE_ROOT` (as the post-publish `test-installation` job already does). See F008.
- [x] Is macOS still a required published platform, in addition to Linux and Windows? — *Owner: maintainer* *(recommended)*: No. Target Linux x86_64 + Windows AMD64; defer macOS. Navigator has never published a macOS wheel, `macos-latest` rows were added and removed in the workflow's history, and navconfig and python-datamodel ship no macOS wheels, so a macOS Navigator wheel would still compile those from sdist on the user's machine. asyncdb does ship macOS x86_64/arm64, so macOS remains a one-row additive change (`CIBW_ARCHS_MACOS: "x86_64 arm64"`) later. See F009.
- [x] Is the Windows target CPython AMD64 for 3.11–3.14, or another ABI/architecture set? — *Owner: maintainer*: `win_amd64` only, cp311–cp314. Every upstream native wheel (navconfig, asyncdb, python-datamodel, xmlsec, pymssql) is `win_amd64`; nobody ships `win_arm64`, and `win32` is skipped as in asyncdb. Free-threaded (`cp31?t-*`) builds are skipped. Navigator cp314 wheels are buildable and should ship, but the post-publish install test on 3.14 stays `continue-on-error` until asyncdb and python-datamodel publish cp314 wheels. See F009, F010.
- [x] Is a concrete Rust/PyO3 extension planned for Navigator now, or should the first refactor remain Cython-only but extensible? — *Owner: maintainer* *(recommended)*: Cython-only, extensible. asyncdb's tracked tree has no `.rs` or `Cargo.toml` and uses `setuptools.build_meta`; its `rst_convert` Rust directory is an untracked local experiment. Keep setuptools (maturin cannot drive Cython; `setuptools-rust`'s `RustExtension` coexists with Cython `Extension` entries), remove the dead rustup step, and document the seam: `setuptools-rust` in `[build-system]`, a `RustExtension`, `CIBW_BEFORE_ALL` rustup, and one more name in the archive check. See F006, F010.
- [x] Are asyncdb and navconfig credible implementation precedents? — *Owner: maintainer*: Yes, with one caveat: navconfig 2.5.1 is the closer precedent (Linux + Windows, cp310–cp314, `uv build --wheel` on `windows-latest`, uvloop platform marker). asyncdb proves the three-OS cibuildwheel matrix and the archive-level check, but not cp314, because its own release skips it (see Round 3). See F010.
