# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
* **Windows and Python 3.14 wheels.** The release pipeline now builds and
  publishes `win_amd64` wheels alongside the existing Linux
  `manylinux_2_28_x86_64` wheels, both for CPython 3.11, 3.12, 3.13, and
  3.14 (FEAT-007). Every published wheel is validated to contain the
  compiled `navigator.types` and `navigator.utils.types` extensions
  (`.so` on Linux, `.pyd` on Windows) before publication; a missing
  extension or unsupported wheel tag now fails the release instead of
  publishing a broken artifact. macOS, `win32`, `win_arm64`,
  free-threaded, `i686`, `musllinux`, and PyPy wheels remain out of
  scope for this release.

### Fixed
* **Release smoke-test crash on a fresh cibuildwheel environment.**
  `navigator/types.pyx` no longer imports `navconfig` at module import
  time — that dead import (unused in the module) bootstrapped
  navconfig's project configuration as a side effect, which raised an
  uncaught `FileExistsError` when the release pipeline's isolated
  post-build test imported `navigator.types` in an empty temporary
  directory. Wheel compilation and `auditwheel`/`delvewheel` repair were
  never affected; only the post-build import smoke test was. `navconfig`
  is unaffected as a runtime dependency of Navigator.

### Changed
* **Build-time dependency boundary.** `navconfig[default]` is no longer
  part of the isolated `[build-system].requires` used to compile
  Navigator's Cython extensions — it remains a full runtime dependency
  via `[project].dependencies`, just not a build-time one.
* **Windows-safe `uvloop`.** Navigator's base dependency on `asyncdb` no
  longer pulls in `asyncdb`'s `uvloop` extra unconditionally; Navigator's
  own `uvloop` and `production` optional-dependency extras are now
  guarded with a `sys_platform != 'win32'` marker, matching the runtime
  behavior in `navigator/utils/uv.py` (uvloop is optional there too).
  Linux/macOS production installs are unaffected.
* `Cython` is now pinned to `>=3.1.4,<4` (up from `>=3.0.11,<4`) across
  `[build-system].requires`, the base dependencies, and the `build`
  extra, aligning with the version required to compile under
  Python 3.14.
* Removed the stale `setup.cfg` `[wheel]` section (`python-tag = py310`,
  `universal = 1`), which no longer matched the compiled-extension wheel
  tags Navigator actually produces.

### Removed
* **BREAKING: `navigator.brokers.*` has been removed entirely** (Redis Streams,
  RabbitMQ, and AWS SQS connection/consumer/producer classes). The broker
  implementations were extracted to the standalone **`navigator-eventbus`**
  package (published `0.1.0rc1`), which also carries the PR #393 fixes
  (RedisConsumer kwargs `TypeError`, opt-in PEL reclaim via `XAUTOCLAIM`, and
  keyword producer credentials). **No compatibility shim / re-export is provided**
  — this is a hard migration.

### Changed
* Consumers of `navigator.brokers.*` MUST migrate their imports to
  `navigator_eventbus.brokers.*` (e.g. `from navigator_eventbus.brokers.sqs
  import SQSConnection`). Class names are unchanged.
* `navigator` now exposes an optional extra: install
  `navigator-api[brokers]` (pins `navigator-eventbus[brokers]>=0.1.0rc1`) to pull
  the ported brokers explicitly. The direct `aiormq` dependency was dropped
  (it was used only by the removed broker code).
* **Coordinated release required.** Known external consumers must migrate their
  imports before this navigator release is cut:
  * **Flowtask** — migrate `navigator.brokers.*` → `navigator_eventbus.brokers.*`.
  * **FieldSync** — migrate imports **and drop its local PR #393 workaround shim**
    (the fix now lives in `navigator-eventbus`).

## [2.3.0] - 2022-10-03
* Add Support for Pluggable Extensions
* Extensions: LocaleSupport (babel+locale), DBConnection (based on asyncdb), Redis (based on aioredis), Memcache (based on aimcache), TemplateParser (based on jinja2), Auth (Authentication Support)
* Refactor Code.

## [2.2.0] - 2022-09-14
* Added python-datamodel as dependency for build Dataclasses.
* replaced rapidjson with orjson.
* fix some issues in publish-to-pypi GH.
* Support for aiohttp > 3.8

## [2.1.0] - 2021-10-20
* First stable version with support to Python +3.8
* Fixing issues over pyproject.toml
