# TASK-042: Scaffold OdooHelpdesk — settings, class, adapter helpers

**Feature**: FEAT-006 — OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)
**Spec**: `sdd/specs/odoo-helpdesk-action.spec.md`
**Jira**: NAV-9101
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task — every other FEAT-006 task builds on this. Implements Spec §3 Module 2 (settings) and the skeleton + private helpers of Module 1. No endpoint logic yet: `create()` is defined as a temporary stub that raises `NotImplementedError` (satisfies the `AbstractTicket.create` abstract method so the module imports; TASK-043 fills it in).

The whole point of FEAT-006 is a **drop-in for `Zammad`** — same bases, same method surface, Zammad-shaped returns. This task sets up the class so it constructs correctly and sets the API-key header the right way (the #1 trap called out in NAV-9101).

---

## Scope

1. **`navigator/conf.py`** — append generic settings near the existing `ZAMMAD_*` block (lines ~243–251):
   ```python
   ODOO_HELPDESK_INSTANCE = config.get('ODOO_HELPDESK_INSTANCE')
   ODOO_HELPDESK_API_KEY  = config.get('ODOO_HELPDESK_API_KEY')
   ODOO_HELPDESK_COMPANY  = config.get('ODOO_HELPDESK_COMPANY')
   ```
   Do **not** add per-tenant `ODOO_<TENANT>_*` here (Spec §8 Q3 — those go to navapi later).

2. **`navigator/actions/odoo_helpdesk.py`** (NEW) — create the class:
   - Imports + `class OdooHelpdesk(AbstractTicket, RESTAction)`.
   - `__init__(self, *args, **kwargs)`: `super().__init__(...)`, then pop `instance`/`api_key`/`company_id`/`as_user` from `self._kwargs` with `ODOO_HELPDESK_*` fallbacks; set `self.headers['X-Helpdesk-Api-Key'] = self.api_key`. Do **NOT** set `auth_type = 'apikey'`.
   - `_company_qs(self, extra: dict | None = None) -> str`: build the query string with **mandatory** `company_id` (raise `ConfigError` if missing) + optional `as_user` + any `extra` params.
   - `_to_zammad_ticket(self, odoo: dict) -> dict`: map one Odoo ticket record to the Zammad-shaped dict per Spec §2 (must include `number` = `odoo['name']`, `id`, `subject`, `body`, flattened `state`/`priority`/`group`/`customer`/`owner`, `attachments`, `extra_fields`, and raw `odoo`).
   - `_parse_attachment_path(self, path: str) -> str`: return the trailing segment id of a Zammad-style `"/{ticket}/{article}/{attachment}"` path.
   - `async def create(self, **kwargs)`: temporary `raise NotImplementedError` (filled by TASK-043).

**NOT in scope**: any real HTTP call, create/update/get/list/articles/attachment logic, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/conf.py` | MODIFY | add 3 `ODOO_HELPDESK_*` settings |
| `navigator/actions/odoo_helpdesk.py` | CREATE | class skeleton, `__init__`, helpers, `create()` stub |

---

## Codebase Contract (Anti-Hallucination)

### Verified imports (confirmed present in this repo)
```python
import base64
from datetime import datetime, timedelta
from io import BytesIO
from aiohttp.web import Request, StreamResponse
from ..exceptions import ConfigError                 # navigator/exceptions.py
from ..conf import (                                  # navigator/conf.py (settings added by this task)
    ODOO_HELPDESK_INSTANCE, ODOO_HELPDESK_API_KEY, ODOO_HELPDESK_COMPANY,
)
from .ticket import AbstractTicket                    # navigator/actions/ticket.py:6
from .rest import RESTAction                          # navigator/actions/rest.py:? (class def)
```

### Base-class facts (verified — do not deviate)
- `AbstractTicket.__init__` (ticket.py:11) pops `self._kwargs['action']` (default `'create'`) and declares abstract `create()`. `run()` only dispatches `'create'`.
- `RESTAction` class attrs: `auth_type = 'key'` (rest.py:40), `token_type = 'Bearer'` (rest.py:41). `__init__` (rest.py:44) builds `self.headers` (rest.py:64) and sets `self.file_buffer = kwargs.pop('file_buffer', False)` (rest.py:57).
- ⚠️ **rest.py:138-142** — if `auth_type == 'apikey'`, `request()` injects `headers['Authorization'] = f"{token_type} {auth['apikey']}"`. This is exactly what NAV-9101 says to avoid → **leave `auth_type` at its inherited default and set `X-Helpdesk-Api-Key` manually**.
- `AbstractAction` provides `__aenter__`/`__aexit__` (abstract.py:65/69) → `async with OdooHelpdesk(...)` works with no extra code.

### Pattern to copy (do NOT modify the source)
```python
# navigator/actions/odoo.py:10-19 — the direct-header API-key idiom
class Odoo(RESTAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = self._kwargs.pop('instance', ODOO_HOST)
        self.api_key  = self._kwargs.pop('api_key', ODOO_APIKEY)
        self.headers['api-key'] = self.api_key   # ← direct header, no auth_type
```

### Does NOT exist yet
- ~~`navigator.actions.odoo_helpdesk`~~ — this task creates it.
- ~~`OdooHelpdesk`~~ — new class; must NOT collide with existing `navigator.actions.odoo.Odoo`.

---

## Implementation Notes

- Mirror `Zammad.__init__` (zammad.py:44-52) for the pop-with-fallback idiom, but for Odoo settings and with the `X-Helpdesk-Api-Key` header instead of `self.auth = {"apikey": ...}`.
- `_to_zammad_ticket` shape is authoritative in Spec §2 ("Zammad-shape adapter contract"). Use `(odoo.get("stage") or {}).get("name")` guards — nested keys can be `null`.
- `_company_qs`: `company_id` missing → `raise ConfigError("company_id is required for Odoo Helpdesk GET calls")` (Spec §7).

---

## Acceptance Criteria

- [ ] `navigator/actions/odoo_helpdesk.py` imports cleanly: `from navigator.actions.odoo_helpdesk import OdooHelpdesk`.
- [ ] `OdooHelpdesk(instance=..., api_key=..., company_id=1, action="create")` constructs; `self.headers['X-Helpdesk-Api-Key']` is set.
- [ ] `OdooHelpdesk.auth_type` is NOT `'apikey'` (inherits `'key'`).
- [ ] `_to_zammad_ticket()` returns a dict containing `number`, `id`, `subject`, `body`.
- [ ] `_parse_attachment_path("/12/34/56") == "56"`.
- [ ] `_company_qs()` raises `ConfigError` when `company_id` is unset.
- [ ] `navigator/conf.py` exposes `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY`.
- [ ] Existing `Odoo` class in `odoo.py` untouched.

---

## Agent Instructions

1. Read the spec (`sdd/specs/odoo-helpdesk-action.spec.md`), §2/§3/§6/§7.
2. Read `navigator/actions/{zammad,odoo,ticket,rest,abstract}.py` before writing.
3. Implement per scope. Keep `create()` a `NotImplementedError` stub.
4. On completion, move this file to `sdd/tasks/completed/` and fill the Completion Note.

---

## Completion Note

Implemented the scaffold, settings, and adapter helpers.

**Files touched:**
- `navigator/conf.py` — added `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY` after the `ZAMMAD_*` block (with a comment noting per-tenant values live in navapi, per Spec §8 Q3).
- `navigator/actions/odoo_helpdesk.py` (NEW) — `class OdooHelpdesk(AbstractTicket, RESTAction)` with `__init__` (pops `instance`/`api_key`/`company_id`/`as_user` with `ODOO_HELPDESK_*` fallbacks; sets `self.headers['X-Helpdesk-Api-Key']`; does NOT set `auth_type='apikey'`), helpers `_company_qs()`, `_to_zammad_ticket()`, `_parse_attachment_path()`, and a `create()` `NotImplementedError` stub.

**Verification (runtime, source on `PYTHONPATH`):** all acceptance checks pass — module imports, `auth_type` stays `'key'`, `X-Helpdesk-Api-Key` set with no `Authorization` header, `_parse_attachment_path('/12/34/56')=='56'`, `_company_qs()` raises `ConfigError` when `company_id` unset, `_to_zammad_ticket()` maps `number`←`name`/`id`/nested `state`/`customer`, `create()` raises `NotImplementedError`. The existing `navigator.actions.odoo.Odoo` still imports unchanged.

**Base-class assumptions confirmed (no NAV-9101 corrections needed for this task):**
- `RESTAction.__init__` builds `self.headers` (rest.py:64) so setting `X-Helpdesk-Api-Key` after `super().__init__()` works.
- `RESTAction.auth_type` default is `'key'` (rest.py:46); the `'apikey'` Bearer-injection branch is at rest.py request-path (confirmed) — correctly avoided.
- `AbstractAction.__init__` leaves popped keys out of `self._kwargs`, and `AbstractTicket` provides the `create` abstract + `run` dispatch; `__aenter__`/`__aexit__` inherited.

**Deployment note (flag, not a blocker):** navapi's venv has `navigator` installed as a **copied** package in `site-packages`, not editable — the running app will not see `odoo_helpdesk.py` until `navigator` is reinstalled/rebuilt in navapi's environment. Verification here was done with the source repo on `PYTHONPATH`. Relevant when the later tenant-migration ticket wires this in.

**Lint nits (intentional, match house style):** `_company_qs(extra: dict = None)` mirrors `Zammad.find_user(search: dict = None)`; the unused `**kwargs` in the `create()` stub is by design (filled in TASK-043).
