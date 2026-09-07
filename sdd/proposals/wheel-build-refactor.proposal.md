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
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-007/
created: 2026-09-08
updated: 2026-09-08
---

# FEAT-007 — Refactor Navigator wheel build infrastructure

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: inline
> **Audit**: [`sdd/state/FEAT-007/`](../state/FEAT-007/)

## 0. Origin

The original request is preserved in [`source.md`](../state/FEAT-007/source.md).

> `$sdd-proposal wheel-build-refactor -- navigator build pipeline is completely broken: https://github.com/phenobarbital/navigator/actions/runs/33763696379/job/100676045151 but also we need to include python 3.14 and Windows in build, then is better to focused this spec in refactor the build infraestructure of navigator package, using as example repositories like ../../asyncdb, with mixed code from cython and Rust and are effectively compiling wheels for python 3.13, 3.14 and Windows support.`

Initial signals: the request reports a broken build, asks for Python 3.14 and Windows, and proposes a build-infrastructure refactor informed by asyncdb. No acceptance criteria beyond those platform/build goals were supplied.

## 1. Synthesis Summary

Navigator currently builds two Cython extensions through `setup.py`, while its release workflow is Linux-only and publishes only manylinux wheels. The packaging metadata also contains a legacy `py310`/`universal` wheel declaration that conflicts with compiled extension behavior. The recommended direction is an explicit cibuildwheel contract for the supported CPython versions and platforms, with archive-level validation for wheel tags and `.so`/`.pyd` contents, modeled on the local asyncdb workflow. Rust/PyO3 or maturin should remain a design option until the project confirms that a Rust extension is needed now; no Rust build contract exists in Navigator today. The exact failure cause remains unconfirmed because the linked Actions log and a complete local build were unavailable. *Evidence: F001–F007.*

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
| C5 | The exact root cause of the linked Actions failure is unknown. | F007 | high | The job log was inaccessible and local build tooling is incomplete. |
| C6 | Immediate Rust integration is not grounded in current Navigator files. | F006 | medium | No tracked Rust build files were found, but the user may want a future native extension. |

Distribution: 3 high, 3 medium, 0 low. Overall confidence remains medium because the missing failure log is central to diagnosis.

## 5. Open Questions

- [ ] What exact error appears in Actions run `33763696379`, job `100676045151`? Possible classes are build backend/Cython compilation, dependency installation, or artifact publication failure. Resolves C5.
- [ ] Should macOS wheels remain part of Navigator’s release promise, or should the target be Linux and Windows only? Resolves C2 and changes the matrix/deploy scope.
- [ ] Should Rust/PyO3 or maturin be introduced now, or should the infrastructure merely remain extensible for a later native module? Resolves C6.
- [ ] Is the Windows target CPython AMD64 for 3.11–3.14, or is another ABI/architecture policy intended? Resolves C2 and determines cibuildwheel selectors.

## 6. Recommended Next Step

**`/sdd-brainstorm wheel-build-refactor`** — the repository localization is strong, but the exact failure is unavailable and the Windows/macOS/Rust decisions create architectural forks. Resolve those choices before producing a formal implementation specification.

### Alternatives

- **`/sdd-spec wheel-build-refactor`** — appropriate after the four open questions are answered.
- **Manual review** — required if the linked Actions failure indicates a dependency or release-policy issue outside the current evidence.

## 7. Research Audit

| Artifact | Path |
|---|---|
| State | `sdd/state/FEAT-007/state.json` |
| Source | `sdd/state/FEAT-007/source.md` |
| Research plan | `sdd/state/FEAT-007/research_plan.json` |
| Findings | `sdd/state/FEAT-007/findings/F001-*.md` through `F007-*.md` |
| Synthesis | `sdd/state/FEAT-007/synthesis.json` |

Budget consumed: 12 / 40 files, 3 / 25 grep calls, 2 / 10 git calls. Research was not truncated. `wikitoolkit` was unavailable; the Actions URL returned a cache miss; the local wheel probe failed because `build` is not installed.

## 8. Provenance

| Field | Value |
|---|---|
| Generated by | `/sdd-proposal` |
| Plan prompt | `sdd/templates/research_plan.prompt.md` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Codex |
