---
type: feature
base_branch: master
jira: NAV-9101
---

# Brainstorm: odoo-helpdesk-action

**Date**: 2026-07-09
**Author**: Claude (from /sdd-fromjira NAV-9101)
**Jira**: [NAV-9101](https://trocglobal.atlassian.net/browse/NAV-9101)
**Status**: exploration
**Recommended Option**: Option A

> **Repo note**: this is the **`navigator` framework repo** (fork `willicab/navigator`), where the action classes actually live. The consumer `navapi` holds a mirror of this brainstorm and the per-tenant credential *values*; the implementation of `OdooHelpdesk` + its tests land **here**, on a branch off `master`.

---

## 1. Problem Statement

We are migrating the 4 Navigator tenant apps (`apps/apple`, `apps/bose`, `apps/pokemon`, `apps/support` in navapi) from creating tickets in Zammad to the new Odoo 19 Helpdesk webhook (`troc_helpdesk` module, repo `Trocdigital/odoo-troc-helpdesk`). The Odoo-side webhook and field mapping (gaps G1–G9) are done — see NAV-9054 and `docs/zammad-odoo-field-mapping.md` in that repo.

**This ticket is gap G10**: a **drop-in replacement action class** for `Zammad` named `OdooHelpdesk`, exposing the exact same method names and returning the exact same Zammad-shaped responses — so migrating a tenant later means only swapping the import and credentials block, with zero changes to view logic or response parsing.

Today, tenant apps use the shared action class like:

```python
async with Zammad(**res) as ticket:
    new_ticket = await ticket.create(**res)
    result = {"ticket": new_ticket, "ticket_number": new_ticket.get("number")}
```

Tenant views parse Zammad-shaped responses directly (`new_ticket.get("number")`, `result['assets']['Ticket']`, first-article `subject`/`body` merges).

## 2. Existing Solutions Research (codebase findings)

Verified against the code in **this repo** (read, not assumed):

- **`navigator/actions/zammad.py`** — `class Zammad(AbstractTicket, RESTAction)`, 465 lines. Class attrs: `auth_type = 'apikey'`, `token_type = 'Bearer'`, `article_base = {"type": "note", "internal": False}`, `data_format = 'raw'`. `__init__` pops `zammad_instance`/`zammad_token` from `self._kwargs` with conf fallbacks and sets `self.auth = {"apikey": token}`. Methods: `create`, `update`, `list_tickets`, `get_ticket`, `get_articles`, `get_attachment_img`, `find_user`, `create_user`, `get_user_token`. Payload fields are consumed via `self._kwargs.pop(...)`; remaining `**kwargs` are spread into the payload.
- **`navigator/actions/ticket.py`** — `AbstractTicket(AbstractAction)`: pops `action` from `_kwargs` (defaults `'create'`), abstract `create()`, `run()` dispatches only `create`.
- **`navigator/actions/abstract.py`** — provides `__aenter__`/`__aexit__` (lines 65–69) and `open()`/`close()` — `async with OdooHelpdesk(...)` works out of the box.
- **`navigator/actions/rest.py`** — `RESTAction`: `self.headers` built in `__init__` (~line 64); `request()` (line 113) is the sync-`requests`-in-executor path returning `(result, error)` where `error['message']` carries the failure; `async_request()` (line 404) is the aiohttp path; `self.file_buffer` (line 57, branches at 338/586) enables the streaming path used by `get_attachment_img`. **Confirmed**: `auth_type == 'apikey'` auto-injects `Authorization: Bearer <auth['apikey']>` (lines 138–142) — the new class must NOT use it; set `self.headers['X-Helpdesk-Api-Key']` directly instead.
- **`navigator/actions/odoo.py`** — ⚠️ **name collision confirmed**: existing `class Odoo(RESTAction)` (39 lines) serving unrelated `fieldservice_order`/`create_lead` webhooks with `ODOO_HOST`/`ODOO_APIKEY` and header `api-key`. Must not be touched. New class goes in a **new file** `navigator/actions/odoo_helpdesk.py` named `OdooHelpdesk`. It is also the pattern to copy for the direct-header API-key idiom.
- **`navigator/conf.py`** — generic `ZAMMAD_*` settings at lines 243–251 (instance, token, user, password, default group/customer/catalog, organization, role). This is where the generic `ODOO_HELPDESK_*` fallbacks belong.
- **navapi `apps/zammad/views.py`** (consumer repo) — imports `ZAMMAD_APPLE_*`, `ZAMMAD_BOSE_*`, `ZAMMAD_POKEMON_*` **from `settings.settings` (navapi)**, generic `ZAMMAD_*` fallback for `support`. `_get_credentials(id_api)` maps tenant → `{zammad_instance, zammad_token, group}`.
- **Tenant callers** (navapi) — `Zammad` is imported/used in `apps/{apple,bose,pokemon,support}/views.py` + `apps/support/__init__.py` (out of scope to edit, but they define the response shapes to preserve).
- **Tests** — no existing tests for `Zammad` were found in this repo; `navigator/tests/actions/test_odoo_helpdesk.py` will be the first in that folder.

### Ticket discrepancy found during research

- **Settings split**: the ticket says to add per-tenant `ODOO_APPLE_*`/`ODOO_BOSE_*`/`ODOO_POKEMON_*` to `navigator/conf.py`, but the existing per-tenant `ZAMMAD_<TENANT>_*` pattern lives in navapi's `settings/settings.py`, **not** in this framework's `conf.py` (which only holds the generic set). Proposal: generic `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY` → `navigator/conf.py` (here, as `__init__` fallbacks); per-tenant values → navapi `settings/settings.py` when the (out-of-scope) tenant migration happens. Flag this back to the ticket per its acceptance criterion #5.

## 3. The Odoo Helpdesk webhook contract (target)

All endpoints require header `X-Helpdesk-Api-Key: <key>`.

| Endpoint | Notes | Success response |
|---|---|---|
| `POST {instance}helpdesk/ticket` | flat JSON; `body`→description (create only); `customer`→partner by email (+`firstname`/`lastname`); `attachments` = `[{filename, data(b64), mime_type}]` w/ server-side MIME whitelist; tenant-prefixed/unknown keys → extra fields; `ctoken`/`login`/`password`/`zammad_*` dropped server-side | `{"ok": true, "ticket_id": <int>, "ticket_name": "<subject>"}` — flat; needs follow-up GET |
| `PUT {instance}helpdesk/ticket/<id>` | same keys, **except** `body` → internal chatter note (not description) | `{"ticket": {...full...}}` |
| `GET {instance}helpdesk/ticket/<id>?company_id=<int>&as_user=<login>` | `company_id` **mandatory** (missing→400, mismatch→404); `as_user` impersonates | `{"ticket": {id, name, subject, description, partner, owner, team, stage, priority, category, company, assignees, extra_fields, attachments}}`; `name` is a sequence like `"TICKET/0042"` — not numeric |
| `GET {instance}helpdesk/tickets?company_id=...&as_user=&team_id=&stage_id=&limit=&offset=` | limit default 80, cap 200, id desc | `{"count": N, "limit": L, "offset": O, "tickets": [...]}` |
| `GET {instance}helpdesk/attachment/<id>?company_id=...&as_user=...` | streams raw binary | binary + `Content-Type`/`Content-Disposition`/`Content-Length` |

Errors: 400 `{"error":"bad_request","detail":...}`, 401 `{"error":"unauthorized"}`, 404 `{"error":"not_found"|"forbidden"|"user_not_found"}`, 500 `{"error":"internal_error"}`.

## 4. Options Explored

### Option A: Mirror class `OdooHelpdesk(AbstractTicket, RESTAction)` in a new file (per ticket)

New file `navigator/actions/odoo_helpdesk.py`, subclassing exactly like `Zammad` and translating each method to the webhook contract + Zammad-shape adapters:

- `__init__`: pop `instance`/`api_key`/`company_id` from `_kwargs` with `ODOO_HELPDESK_*` conf fallbacks; **no** `auth_type = 'apikey'`; set `self.headers['X-Helpdesk-Api-Key']` directly (copy the header idiom from `Odoo`).
- `create(**kwargs)`: POST → GET `ticket_id` → adapt to Zammad shape **including a `number` key** (callers do `new_ticket.get("number")`; map from Odoo `name`, e.g. `"TICKET/0042"` — keep as string, callers only `.get()` it).
- `update(ticket, **kwargs)`: PUT → adapt `{"ticket": {...}}` to Zammad shape (`body` becomes chatter note server-side; don't try to read a description change back).
- `get_ticket(ticket_id, user=None)`: GET with mandatory `company_id`, optional `as_user` → Zammad shape with top-level `subject`/`body`.
- `get_articles(ticket_id)`: synthetic single-element article list built from `get_ticket()` (Odoo has no articles).
- `list_tickets(user=None, **kwargs)`: GET list → `{tickets, tickets_count, assets: {Ticket: {<id>: {...}}}}`; **drop** Zammad-only `state_id` kwarg.
- `get_attachment_img(attachment, request, user=None)`: parse trailing id from Zammad-style path `"/{ticket}/{article}/{attachment}"`; `self.file_buffer = True`; stream mirroring Zammad's version.
- `find_user`/`create_user`: truthy no-ops (server auto-creates partner from `customer`), so `if not result: await user.create_user()` branches never fire.
- Use `request()` (executor path) for create/update/get/list — matching Zammad's own usage; `async_request`/`file_buffer` path only for attachment download.

✅ **Pros:** exactly what the ticket asks; zero risk to existing `Zammad`/`Odoo` classes; tenant migration later = import + credentials swap only; test surface is clean (mock `request`/`async_request`).
❌ **Cons:** shape-adaptation logic lives inline in one class (some duplication of "Odoo ticket → Zammad dict" across methods — mitigate with one private `_to_zammad_shape(ticket: dict)` helper).
📊 **Effort:** Medium (1 file ~300 lines + conf + ~6 test areas)

🔗 **Existing Code to Reuse:**
- `navigator/actions/zammad.py` — structure, `_kwargs.pop()` idiom, error handling (`ConfigError` w/ `error['message']`), attachment streaming.
- `navigator/actions/odoo.py` — direct-header API-key idiom (`self.headers['api-key'] = ...`), `_kwargs.pop('instance', CONF)` fallback idiom.
- navapi `apps/zammad/views.py::_get_credentials()` — per-tenant credential mapping for the later migration ticket.

### Option B: Shared adapter/translator module + thin action class

Split the Zammad-shape mapping into `navigator/actions/_odoo_helpdesk_adapter.py` (pure functions: `to_zammad_ticket()`, `to_zammad_list()`, `parse_attachment_path()`), action class calls them.

✅ **Pros:** pure functions trivially unit-testable without mocking HTTP; reusable if other consumers appear.
❌ **Cons:** deviates from the single-file pattern of every other action in `navigator/actions/`; two files to review; ticket frames one new file.
📊 **Effort:** Medium

### Option C: Subclass `Zammad` and override endpoints

✅ **Pros:** least code.
❌ **Cons:** inherits `auth_type = 'apikey'` (exactly the Bearer-header bug the ticket warns about), inherits Zammad conf imports and article semantics; fragile coupling. **Rejected.**

## 5. Recommendation

**Option A**, with Option B's spirit folded in as *private methods* on the class (`_to_zammad_shape()`, `_parse_attachment_path()`) — single file per repo convention, but mapping logic isolated and directly testable.

## 6. Constraints & Non-Goals (from ticket)

- Do **not** edit navapi's `apps/{apple,bose,pokemon,support}/views.py` — tenant swap is a later ticket.
- Do **not** touch the existing `Odoo` class in `navigator/actions/odoo.py`.
- G7 (taxonomy import as Odoo master data) is out of scope.
- The webhook contract above may not be 100% final — flag discrepancies found against a real instance rather than silently guessing.
- Do **not** set `auth_type = 'apikey'` on the new class.

## 7. Acceptance Criteria (from NAV-9101)

- [ ] `navigator/actions/odoo_helpdesk.py` exists with class `OdooHelpdesk` (RESTAction-based, matching the real `AbstractTicket`/`RESTAction` contracts).
- [ ] Settings added following the existing per-tenant pattern (see Discrepancy: generic → `navigator/conf.py` here; per-tenant → navapi `settings/settings.py` at migration time).
- [ ] Tests in `navigator/tests/actions/test_odoo_helpdesk.py` (HTTP layer mocked) covering:
  1. `create()` POST payload + two-step POST→GET adapted to Zammad shape with `number` key.
  2. `update()` PUT + adaptation, including `body`-as-note (no description read-back).
  3. `list_tickets()` adaptation to `{tickets, tickets_count, assets.Ticket}`; `state_id` dropped.
  4. `get_attachment_img()` trailing-id extraction from `"/12/34/56"`.
  5. `find_user()`/`create_user()` truthy no-ops.
  6. `X-Helpdesk-Api-Key` set; no `Authorization: Bearer` header injected.
- [ ] No changes to the existing `Odoo` class or any tenant view file.
- [ ] Completion note lists exact file paths touched + any base-class assumption from the ticket that proved wrong.

## 8. References

- [NAV-9101](https://trocglobal.atlassian.net/browse/NAV-9101) — this ticket (G10)
- NAV-9054 — Zammad → Odoo Helpdesk field inventory and mapping
- `docs/zammad-odoo-field-mapping.md` and `docs/postman/TESTING_GUIDE.md` in `Trocdigital/odoo-troc-helpdesk`, branch `19.0_staging`
- Consumer repo (tenant views, per-tenant settings): `navapi` (`~/work/navigator-new/navapi`)
