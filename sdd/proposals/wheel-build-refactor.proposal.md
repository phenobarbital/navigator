---
id: FEAT-007
title: Refactor Navigator wheel build infrastructure
slug: wheel-build-refactor
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-08
  summary_oneline: Refactor Navigator wheel infrastructure for Cython, future native code, Python 3.13/3.14, and Windows artifacts.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-007/
created: 2026-09-08
updated: 2026-09-08
---

# FEAT-007 — Refactor Navigator wheel build infrastructure

> **Mode**: enrichment
> **Confidence**: high
> **Source**: inline
> **Audit**: [`sdd/state/FEAT-007/`](../state/FEAT-007/)

## 0. Origin

The original request is preserved in [`source.md`](../state/FEAT-007/source.md).

> `$sdd-proposal wheel-build-refactor -- navigator build pipeline is completely broken: https://github.com/phenobarbital/navigator/actions/runs/33763696379/job/100676045151 but also we need to include python 3.14 and Windows in build, then is better to focused this spec in refactor the build infraestructure of navigator package, using as example repositories like ../../asyncdb, with mixed code from cython and Rust and are effectively compiling wheels for python 3.13, 3.14 and Windows support.`

Initial signals: the request reports a broken build, asks for Python 3.14 and Windows, and proposes a build-infrastructure refactor informed by asyncdb. No acceptance criteria beyond those platform/build goals were supplied.

## 1. Synthesis Summary

Navigator currently builds two Cython extensions through `setup.py`, while its release workflow is Linux-only and publishes only manylinux wheels. The packaging metadata also contains a legacy `py310`/`universal` wheel declaration that conflicts with compiled extension behavior. The recommended direction is an explicit cibuildwheel contract for the supported CPython versions and platforms, with archive-level validation for wheel tags and `.so`/`.pyd` contents, modeled on the local asyncdb workflow. Rust/PyO3 or maturin should remain a design option until the project confirms that a Rust extension is needed now; no Rust build contract exists in Navigator today. The linked Actions failure is now confirmed: the wheel compiled and repaired correctly, and the job died in cibuildwheel's post-build import test because `navigator/types.pyx` imports `navconfig` at module load, which hard-fails without a scaffolded `env/` directory. The four open questions below are resolved with evidence from the Actions logs, PyPI metadata, and the asyncdb/navconfig sibling repositories. *Evidence: F001–F010.*

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|---|---|---:|---|---|
| 1 | `pyproject.toml` | `[build-system]`, `[project]`, `[tool.setuptools.packages.find]` | 1–9, 31–51, 207–221 | Build backend, Python metadata, and package discovery | F001 |
| 2 | `setup.py` | `extensions`, `setup()` | 9–56 | Cythonizes `navigator.utils.types` and `navigator.types` | F001 |
| 3 | `setup.cfg` | `[wheel]` | 1–4 | Legacy wheel tag declarations | F001 |
| 4 | `.github/workflows/release.yml` | `build`, `deploy`, `test-installation` | 7–224 | Builds, verifies, publishes, and tests release artifacts | F002, F003 |
| 5 | `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml` | `build`, `deploy` | 7–125 | Comparison pattern for multi-platform cibuildwheel production | F004 |

### 2.2 Constraints Discovered

- Navigator has both C and C++ Cython extensions, so validation must accept platform-specific compiled names and the build must work with platform compilers. *Evidence: F001*
- The current release workflow only requests Ubuntu builds for CPython 3.11–3.13; deployment and structural checks are manylinux-specific. *Evidence: F002*
- The latest build fix made package discovery and compiled-extension presence explicit, and the workflow already has a Python 3.13 dependency-installation exception. *Evidence: F003*
- asyncdb validates wheel archives without installing its complete optional dependency graph and separates Windows `.pyd` checks from Unix `.so` checks. *Evidence: F004, F005*
- No Rust source, Cargo manifest, PyO3 module, or maturin configuration is present in Navigator. *Evidence: F006*

## 3. Probable Scope

### What’s New

- A release build contract for CPython 3.13 and 3.14, Windows AMD64, and the retained supported platforms.
- Archive-level wheel validation for filename tags and required compiled extensions, including `.pyd` on Windows and `.so` on Unix.
- Focused packaging/import smoke tests that do not require every optional integration dependency.

### What Changes

- `pyproject.toml`, `setup.py`, and `setup.cfg`: make the build metadata and native-extension declarations authoritative and internally consistent. *Evidence: F001*
- `.github/workflows/release.yml`: express the OS/version matrix explicitly, build Windows wheels, aggregate all artifacts, validate them before publication, and test installation on the supported matrix. *Evidence: F002, F004, F005*
- Packaging tests: follow asyncdb’s synthetic archive and platform-specific extension checks. *Evidence: F005*

### What’s Untouched (Non-Goals)

- Navigator runtime APIs and application behavior.
- Broad provider or integration rewrites unless dependency analysis proves they block Windows installation.
- Implementing a Rust extension immediately; Navigator has no current Rust source contract. *Evidence: F006*
- Publishing artifacts during development or changing PyPI credentials/environments.

### Patterns to Follow

- Use cibuildwheel with explicit CPython selectors and Windows AMD64 architecture. *Evidence: F004*
- Validate every wheel archive before publication, including platform tag and compiled-extension suffix. *Evidence: F004, F005*
- Keep structural/archive validation independent from full optional dependency installation. *Evidence: F005*

### Integration Risks

- Navigator’s dependency graph may fail on Windows independently of Navigator’s own Cython compilation. The build refactor must distinguish wheel compilation, wheel contents, and installation smoke tests. *Evidence: F002, F003*
- Leaving `setup.cfg`’s legacy wheel declarations authoritative may produce misleading compatibility tags. *Evidence: F001*
- Introducing Rust tooling before a concrete Rust module exists would add CI/build complexity without a current source consumer. *Evidence: F006*

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|---|---|---|---|---|
| C1 | Navigator uses setuptools and compiles two Cython extensions. | F001 | high | Direct reads of packaging and setup files. |
| C2 | The release workflow does not build/publish Windows wheels or request Python 3.14. | F002 | high | Direct read of the matrix, cibuildwheel environment, and deploy filters. |
| C3 | `setup.cfg` contains stale legacy wheel declarations. | F001 | medium | The declarations are present; their exact precedence needs a build-metadata probe. |
| C4 | asyncdb is a viable pattern for cross-platform wheel production and lightweight extension validation. | F004, F005 | high | Direct reads of the local comparison workflow and portability contracts. |
| C5 | The linked Actions failure is an import-time navconfig bootstrap error inside cibuildwheel's test command, not a compilation failure. | F008 | high | Direct read of both job logs; cp313 only passed because its test was skipped. |
| C6 | Immediate Rust integration is not grounded in Navigator or in the asyncdb reference. | F006, F010 | high | Neither repository tracks Rust sources or a Rust build backend; Navigator's rustup step is unused. |
| C7 | Windows AMD64 is the only viable Windows target, and `uvloop` in the base extras blocks Windows installs. | F009 | high | Every upstream native wheel is `win_amd64` only; uvloop has no Windows wheels. |
| C8 | Navigator cp314 wheels are buildable now, but asyncdb and python-datamodel ship no cp314 wheels yet. | F009, F010 | high | PyPI file lists; asyncdb's own release silently skips cp314 via cibuildwheel 2.23.4. |

Distribution: 7 high, 1 medium, 0 low. Overall confidence is high: the failure log has been read end to end and the platform decisions are backed by published upstream artifacts.

## 5. Open Questions

All four questions are resolved (2026-09-08). Decisions marked *recommended* are evidence-backed defaults that the owner can flip before `/sdd-spec`.

- [x] **What exact error appears in Actions run `33763696379`, job `100676045151`?** — Resolved (C5, F008).
  **Class: test-harness / import-time coupling.** Build and `auditwheel` repair succeeded (`manylinux_2_17`-eligible). The `CIBW_TEST_COMMAND` runs in an empty temp directory and executes `import navigator.types`; `navigator/types.pyx:7` does `from navconfig import config, DEBUG`, navconfig's lazy `__getattr__` runs `bootstrap()`, and `BaseLoader.__init__` raises `FileExistsError: NavConfig could not find the expected environment directory. Looked for: /tmp/tmp.yrcnYmd8BK/env`. The guard in `navigator/__init__.py` covers only `Application`, not an explicit `navigator.types` import. cp311 and cp312 fail identically; cp313 passed only because `CIBW_TEST_SKIP: cp313-*` skipped the test. `config` and `DEBUG` are never used in `types.pyx`, so the import is dead code.
  **Spec implications**: (1) delete the unused navconfig import from `navigator/types.pyx`; (2) make the archive-level `.so`/`.pyd` check the blocking gate and replace the inline shell test with a cross-platform Python smoke script that scaffolds `env/<env>/.env` and `SITE_ROOT` before importing (the post-publish `test-installation` job already does this scaffolding); (3) bump `pypa/cibuildwheel` from v2.21.3 (no cp314) to v4.x; (4) remove the unused rustup install from `CIBW_BEFORE_BUILD`; (5) drop `navconfig[default]` from `[build-system].requires`, since `setup.py` never imports it; (6) re-evaluate `CIBW_TEST_SKIP: cp313-*`, whose cassandra-driver rationale is stale.

- [x] **Should macOS wheels remain part of the release promise?** — Resolved *(recommended)*: **Linux x86_64 + Windows AMD64 only; macOS deferred** (C2, F009).
  Navigator has never published a macOS wheel (every release 3.1.0–3.2.2 is manylinux + sdist); `macos-latest` rows were added to the matrix once and later removed. navconfig and python-datamodel publish no macOS wheels, so a macOS Navigator wheel would still compile those two from sdist on the user's machine, and macOS runners bill at 10× Linux minutes. asyncdb does ship macOS x86_64/arm64, so nothing blocks adding macOS later as a single matrix row with `CIBW_ARCHS_MACOS: "x86_64 arm64"`. The spec should make the matrix data-driven so macOS is an additive change.

- [x] **Should Rust/PyO3 or maturin be introduced now?** — Resolved *(recommended)*: **No Rust now; keep the seam open** (C6, F006, F010).
  asyncdb's tracked tree has no `.rs` files, no `Cargo.toml`, and uses `setuptools.build_meta`; its `rst_convert` Rust directory is an untracked local experiment. Navigator's rustup install in the workflow is consumed by nothing. Keep setuptools as the backend: maturin cannot drive Cython extensions, whereas `setuptools-rust`'s `RustExtension` coexists with Cython `Extension` entries in `setup.py`. A future Rust module therefore needs only: `setuptools-rust` in `[build-system]`, a `RustExtension` entry, `CIBW_BEFORE_ALL` rustup on Linux/Windows, and one more required-artifact name in the archive check. The spec should document that extension point and nothing more.

- [x] **Is the Windows target CPython AMD64 for 3.11–3.14?** — Resolved: **Yes, `win_amd64` only, cp311–cp314** (C7, C8, F009).
  navconfig 2.5.1 (2026-09-07) ships `win_amd64` for cp310–cp314; asyncdb, python-datamodel, xmlsec and pymssql ship `win_amd64`; no upstream ships `win32` or `win_arm64`, so those are skipped (`*-win32`, no ARM64). Two dependency constraints the spec must carry: (1) `asyncdb[uvloop,…]` in the base dependencies pulls `uvloop==0.21.0`, which has no Windows wheels and blocks `pip install navigator-api` on Windows; move `uvloop` out of the base extras and guard it with `sys_platform != 'win32'` as navconfig 2.5.1 does (`navigator/__init__.py` already tolerates a missing uvloop). (2) asyncdb and python-datamodel publish no cp314 wheels yet (asyncdb's release pins host Python 3.10, gets cibuildwheel 2.23.4, and silently skips cp314), so Navigator's cp314 wheels are buildable and should ship, but the post-publish install test for 3.14 must be `continue-on-error` until those upstreams publish cp314 wheels. Free-threaded builds (`cp31?t-*`) are skipped: orjson and others ship no free-threaded wheels.

## 6. Recommended Next Step

**`/sdd-spec wheel-build-refactor`** — the four open questions are answered with direct evidence, so the architectural forks are closed: Linux x86_64 + Windows AMD64, cp311–cp314, setuptools + Cython with cibuildwheel v4, no Rust yet. The spec should split the work into (a) the two-line hotfix that unblocks releases today (drop the dead navconfig import in `navigator/types.pyx`, or scaffold `SITE_ROOT` in the test), and (b) the matrix/validation refactor.

### Alternatives

- **Hotfix first on `main`** — the root cause is a one-line dead import; shipping that alone restores the Linux release pipeline before the refactor lands.
- **`/sdd-brainstorm wheel-build-refactor`** — only if the owner wants to reopen the macOS or Rust recommendations above.

## 7. Research Audit

| Artifact | Path |
|---|---|
| State | `sdd/state/FEAT-007/state.json` |
| Source | `sdd/state/FEAT-007/source.md` |
| Research plan | `sdd/state/FEAT-007/research_plan.json` |
| Findings | `sdd/state/FEAT-007/findings/F001-*.md` through `F010-*.md` (F008–F010 added while resolving the open questions) |
| Synthesis | `sdd/state/FEAT-007/synthesis.json` |

Budget consumed: 12 / 40 files, 3 / 25 grep calls, 2 / 10 git calls. Research was not truncated. `wikitoolkit` was unavailable; the Actions URL returned a cache miss; the local wheel probe failed because `build` is not installed. Follow-up (2026-09-08): the Actions logs were fetched with `gh api`, PyPI metadata was queried for the native dependency chain, and the asyncdb/navconfig sibling repositories were inspected; see F008–F010.

## 8. Provenance

| Field | Value |
|---|---|
| Generated by | `/sdd-proposal` |
| Plan prompt | `sdd/templates/research_plan.prompt.md` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Codex |
