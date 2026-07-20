# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
