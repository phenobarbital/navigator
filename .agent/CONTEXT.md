# Navigator — Architectural Context

## What is Navigator

Navigator is an async Python web framework built on `aiohttp` and `asyncio`.
It provides application lifecycle management, class-based views, brokers,
background services, configuration helpers, and integrations such as Odoo,
Zammad, HubSpot, and Google APIs.

## Core areas

- `navigator/applications/` — application configuration and startup lifecycle.
- `navigator/views/` — request handlers and class-based view abstractions.
- `navigator/actions/` — integrations and external service actions.
- `navigator/services/` — background and long-running services.
- `navigator/brokers/` — RabbitMQ, MQTT, Redis, and SQS broker support.
- `navigator/utils/` — shared helpers and typed utility modules.
- `scripts/sdd/` — SDD metadata, ID allocation, validation, and closeout tools.

## Engineering patterns

- Keep request handlers and services asynchronous; do not block the event
  loop.
- Use existing Navigator abstractions and dependency files before introducing
  imports or new dependencies.
- Preserve public import paths and type annotations when implementing a task.
- Use `black` and `isort` for Python formatting and run focused pytest checks
  relevant to the changed area.
- Keep credentials and environment-specific configuration outside source code.

## SDD conventions

- Feature work normally starts from `dev`; `staging` is valid during a release
  freeze. Hotfixes use `main`.
- Feature specs must not use `main` as their base branch.
- Feature and task IDs are allocated with `scripts.sdd.reserve_ids`; do not
  hand-compute IDs.
- Current SDD scripts support per-spec indexes at
  `sdd/tasks/index/<feature-slug>.json`. The historical monolithic
  `sdd/tasks/.index.json` remains for legacy task records.
- Worktrees use `.claude/worktrees/` for compatibility with existing SDD
  scripts.
- Implementation changes and SDD state updates belong in the same worktree
  branch. Use `scripts/sdd/close_task.sh` for task closure.

## Validation commands

```bash
make format
make lint
make test
```

For SDD-only changes, validate the relevant scripts and tests under
`tests/sdd_scripts/`, and store persistent test output under
`artifacts/logs/`.
