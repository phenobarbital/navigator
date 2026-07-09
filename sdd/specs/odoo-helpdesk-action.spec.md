# Feature Specification: OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)

**Feature ID**: FEAT-006
**Date**: 2026-07-09
**Author**: Claude (from /sdd-spec, brainstorm `odoo-helpdesk-action`)
**Jira**: [NAV-9101](https://trocglobal.atlassian.net/browse/NAV-9101)
**Status**: draft
**Target version**: next
**Base branch**: `master`

---

## 1. Motivation & Business Requirements

### Problem Statement

The 4 Navigator tenant apps (`apps/apple`, `apps/bose`, `apps/pokemon`, `apps/support`, all in the **navapi** consumer repo) create support tickets in Zammad through the shared action class `navigator/actions/zammad.py` (`class Zammad(AbstractTicket, RESTAction)`). Tickets are now migrating to the new Odoo 19 Helpdesk webhook (`troc_helpdesk`, repo `Trocdigital/odoo-troc-helpdesk`). The Odoo side (gaps G1–G9) is complete. This spec covers **G10**: the piece that lives in the Navigator framework — a new action class that talks to the Odoo Helpdesk webhook while presenting the **exact same method surface and Zammad-shaped return values** as `Zammad`, so a later per-tenant migration is just an import + credentials swap with zero changes to tenant view logic or response parsing.

### Goals
- Add `class OdooHelpdesk(AbstractTicket, RESTAction)` in a **new file** `navigator/actions/odoo_helpdesk.py`.
- Mirror `Zammad`'s public methods (`create`, `update`, `get_ticket`, `list_tickets`, `get_articles`, `get_attachment_img`, `find_user`, `create_user`) with identical signatures and Zammad-shaped return dicts.
- Talk to the Odoo Helpdesk webhook (`POST/PUT/GET helpdesk/ticket[s]`, `GET helpdesk/attachment/<id>`) using header `X-Helpdesk-Api-Key`.
- Add generic `ODOO_HELPDESK_*` settings to `navigator/conf.py` as `__init__` fallbacks.
- Ship unit tests with the HTTP layer mocked.

### Non-Goals (explicitly out of scope)
- Editing navapi tenant views (`apps/{apple,bose,pokemon,support}/views.py`) — the `Zammad`→`OdooHelpdesk` swap is a separate later ticket.
- Modifying or renaming the existing `Odoo` class in `navigator/actions/odoo.py`.
- Adding per-tenant `ODOO_<TENANT>_*` values to navapi's `settings/settings.py` — deferred to the migration ticket (see §8, Q3).
- G7 (importing `service_catalog`/`zammad_groups` taxonomy as Odoo master data).
- Guaranteeing the webhook contract is 100% final — discrepancies found against a live instance are flagged, not silently coded around.

---

## 2. Architectural Design

### Overview

`OdooHelpdesk` subclasses the same bases as `Zammad` (`AbstractTicket` for the `async with ... as ticket:` + `_action_` dispatch, `RESTAction` for the HTTP layer). It stores per-instance `instance`/`api_key`/`company_id` (popped from kwargs with `ODOO_HELPDESK_*` conf fallbacks) and sets the API-key header **directly** — it does **not** set `auth_type = 'apikey'`, which would make `RESTAction` inject an `Authorization: Bearer` header the Odoo webhook rejects.

Each public method translates the Zammad call into the Odoo webhook contract and adapts the Odoo response back into a Zammad-shaped dict via two private helpers:
- `_to_zammad_ticket(odoo_ticket: dict) -> dict` — maps one Odoo ticket record to the flat Zammad ticket dict (including the `number` key downstream callers rely on).
- `_parse_attachment_path(path: str) -> str` — extracts the trailing attachment id from a Zammad-style `"/{ticket}/{article}/{attachment}"` path.

### Component Diagram
```
async with OdooHelpdesk(**res) as ticket:        (navapi tenant view — future)
        │
        ├── create()  ── POST helpdesk/ticket ──► {ok,ticket_id,ticket_name}
        │                └─ GET helpdesk/ticket/<id> ──► _to_zammad_ticket() ──► {number, id, subject, body, ...}
        ├── update()  ── PUT  helpdesk/ticket/<id> ──► {ticket:{...}} ─► _to_zammad_ticket()
        ├── get_ticket() ─ GET helpdesk/ticket/<id> ─► _to_zammad_ticket()
        ├── get_articles() ─ (calls get_ticket) ─► [ synthetic single article ]
        ├── list_tickets() ─ GET helpdesk/tickets ─► {tickets, tickets_count, assets:{Ticket:{...}}}
        ├── get_attachment_img() ─ GET helpdesk/attachment/<id> ─► StreamResponse
        └── find_user()/create_user() ─► truthy no-op
                            ▲
              RESTAction.request()/async_request()  (headers['X-Helpdesk-Api-Key'])
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.actions.ticket.AbstractTicket` | extends | `_action_` dispatch, abstract `create()`, `run()` |
| `navigator.actions.rest.RESTAction` | extends | HTTP layer; `request()` (executor) for CRUD, `async_request()`/`file_buffer` for attachment stream |
| `navigator.actions.abstract.AbstractAction` | inherited via AbstractTicket | provides `__aenter__`/`__aexit__`, `open()`/`close()` |
| `navigator.conf` | reads | new `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY` |
| `navigator.actions.odoo.Odoo` | pattern-only (NOT modified) | copy the direct-header API-key idiom (`self.headers['api-key']=...`) |
| `navigator.exceptions.ConfigError` | raises | same error idiom as `Zammad` (`error['message']`) |

### The Odoo Helpdesk webhook contract (target system)

All endpoints require header `X-Helpdesk-Api-Key: <key>`. `{instance}` is a base URL ending in `/`.

| Method + path | Request | Success (200) | Errors |
|---|---|---|---|
| `POST {instance}helpdesk/ticket` | flat JSON body (`title`/`subject`, `body`→description **create only**, `customer`→partner by email +opt `firstname`/`lastname`, `owner`→user by login, `group`→team fallback, `type`, `state`/`state_name`→stage, `priority`/`priority_id`, `attachments`=`[{filename,data(b64),mime_type}]`, `organization_id`→company+category routing, `contact_name`→person_name; tenant-prefixed & unknown keys→extra fields; `ctoken`/`login`/`password`/`user_credentials`/`zammad_instance`/`zammad_token` dropped server-side) | `{"ok": true, "ticket_id": <int>, "ticket_name": "<subject>"}` (flat, no nested ticket → needs follow-up GET) | 400 `{"error":"bad_request","detail":"..."}`, 401 `{"error":"unauthorized"}`, 500 `{"error":"internal_error"}` |
| `PUT {instance}helpdesk/ticket/<id>` | same key semantics **except** `body`→internal chatter note (not description) | `{"ticket": {...fully serialized...}}` | 404 `{"error":"not_found",...}`, 401, 500 |
| `GET {instance}helpdesk/ticket/<id>?company_id=<int>&as_user=<login>` | `company_id` **mandatory** (missing→400, mismatch→404); `as_user` impersonates | `{"ticket": {id, name, subject, description, partner:{id,name}\|null, owner, team, stage, priority, category, company, assignees:[{id,name}], extra_fields:[{field_name,value}], attachments:[{id,name}]}}`; `name` is a sequence like `"TICKET/0042"` (NOT numeric) | 404 not_found/forbidden, 404 `{"error":"user_not_found","as_user":"..."}`, 401, 400 |
| `GET {instance}helpdesk/tickets?company_id=&as_user=&team_id=&stage_id=&limit=&offset=` | `company_id` mandatory; `limit` default 80, cap 200 | `{"count": N, "limit": L, "offset": O, "tickets": [<single-ticket shape>...]}` id desc | as above |
| `GET {instance}helpdesk/attachment/<id>?company_id=&as_user=` | `company_id` mandatory | raw binary + `Content-Type`/`Content-Disposition`/`Content-Length` | same company_id/not_found/forbidden pattern |

### Zammad-shape adapter contract

`_to_zammad_ticket(odoo)` produces (at minimum) the keys tenant views read today:

```python
{
    "id": odoo["id"],
    "number": odoo["name"],           # "TICKET/0042" — callers do .get("number"); see §8 Q1
    "title": odoo.get("subject"),
    "subject": odoo.get("subject"),   # top-level, no article wrapping (get_ticket contract)
    "body": odoo.get("description"),
    "state": (odoo.get("stage") or {}).get("name"),
    "priority": (odoo.get("priority") or {}).get("name"),
    "group": (odoo.get("team") or {}).get("name"),
    "customer": (odoo.get("partner") or {}).get("name"),
    "owner": (odoo.get("owner") or {}).get("name"),
    "attachments": odoo.get("attachments", []),
    "extra_fields": odoo.get("extra_fields", []),
    # raw Odoo record preserved for forward-compat:
    "odoo": odoo,
}
```

`list_tickets` wraps these into Zammad's list shape:
```python
{
    "tickets": [<ids or ticket dicts, matching Zammad>],
    "tickets_count": count,
    "assets": {"Ticket": {str(t["id"]): _to_zammad_ticket(t) for t in tickets}},
}
```

`get_articles(ticket_id)` returns a **synthetic single-element list** (Odoo has no article concept):
```python
[{
    "id": ticket_id,
    "subject": z["subject"],
    "body": z["body"],
    "attachments": z["attachments"],
}]
```

---

## 3. Module Breakdown

### Module 1: OdooHelpdesk action class
- **Path**: `navigator/actions/odoo_helpdesk.py` (NEW)
- **Responsibility**: `class OdooHelpdesk(AbstractTicket, RESTAction)`. `__init__` pops `instance`/`api_key`/`company_id`/`as_user` from `self._kwargs` with `ODOO_HELPDESK_*` fallbacks, sets `self.headers['X-Helpdesk-Api-Key'] = self.api_key` (no `auth_type='apikey'`). Public methods `create`, `update`, `get_ticket`, `list_tickets`, `get_articles`, `get_attachment_img`, `find_user`, `create_user`. Private helpers `_to_zammad_ticket`, `_parse_attachment_path`, `_company_qs()` (build mandatory `company_id`+optional `as_user` query string). Uses `request()` for CRUD, `async_request()`+`file_buffer` for attachment stream. Raises `ConfigError(f"...: {error['message']}")` on `error is not None`.
- **Depends on**: `navigator.actions.ticket.AbstractTicket`, `navigator.actions.rest.RESTAction`, `navigator.exceptions.ConfigError`, `navigator.conf` (new settings), stdlib (`base64`, `datetime`, `io.BytesIO`), `aiohttp.web` (`Request`, `StreamResponse`).

### Module 2: Settings
- **Path**: `navigator/conf.py` (MODIFY — append near the `ZAMMAD_*` block, lines ~243–251)
- **Responsibility**: declare generic fallbacks used by `OdooHelpdesk.__init__`:
  ```python
  ODOO_HELPDESK_INSTANCE = config.get('ODOO_HELPDESK_INSTANCE')
  ODOO_HELPDESK_API_KEY  = config.get('ODOO_HELPDESK_API_KEY')
  ODOO_HELPDESK_COMPANY  = config.get('ODOO_HELPDESK_COMPANY')
  ```
  Per-tenant `ODOO_<TENANT>_*` values are intentionally **not** added here — see §8 Q3.
- **Depends on**: `navconfig.config` (already imported in `conf.py`).

### Module 3: Tests
- **Path**: `navigator/tests/actions/test_odoo_helpdesk.py` (NEW; create `navigator/tests/actions/` if absent)
- **Responsibility**: unit tests with the HTTP layer mocked (patch `OdooHelpdesk.request` / `.async_request`), covering the 6 areas in §4.
- **Depends on**: `pytest`, `pytest-asyncio`, `unittest.mock`.

---

## 4. Test Specification

### Unit Tests
| Test | Verifies |
|---|---|
| `test_create_builds_post_payload_and_adapts` | `create()` POSTs a flat body with mapped keys, then GETs `ticket_id`; returns a Zammad-shaped dict whose `number` == Odoo `name`; `id` == `ticket_id`. |
| `test_create_two_step_post_then_get` | Exactly two HTTP calls: POST `helpdesk/ticket` then GET `helpdesk/ticket/<returned_id>` with mandatory `company_id`. |
| `test_create_raises_on_error` | When `request()` returns `(None, {"message": "..."})`, raises `ConfigError` carrying the message. |
| `test_update_sends_put_and_adapts` | `update(ticket, ...)` PUTs to `helpdesk/ticket/<id>` and adapts `{"ticket":{...}}` into Zammad shape. |
| `test_update_with_body_no_description_readback` | When payload includes `body`, `update()` does not assert/read a description change from the response (body → chatter note server-side). |
| `test_list_tickets_adapts_shape` | `{count,limit,offset,tickets}` → `{tickets, tickets_count, assets:{Ticket:{<id>:{...}}}}`. |
| `test_list_tickets_drops_state_id` | A Zammad-only `state_id` kwarg is dropped, not forwarded to the query string. |
| `test_get_ticket_top_level_subject_body` | `get_ticket()` returns `subject`/`body` at top level (no article wrapping); sends mandatory `company_id`, optional `as_user`. |
| `test_get_articles_synthetic_single` | `get_articles()` returns a 1-element list built from `get_ticket()` with `id`/`subject`/`body`/`attachments`. |
| `test_get_attachment_img_parses_trailing_id` | `_parse_attachment_path("/12/34/56")` → `"56"`; the GET hits `helpdesk/attachment/56`. |
| `test_find_user_and_create_user_are_truthy_noops` | Both return a truthy value without making an HTTP call, so `if not result: await user.create_user()` never fires. |
| `test_api_key_header_set_no_bearer` | `X-Helpdesk-Api-Key` present on `self.headers`; no `Authorization` header is added (confirms `auth_type` not inherited as `'apikey'`). |

### Test Data / Fixtures
```python
@pytest.fixture
def odoo_ticket_record():
    return {
        "id": 42, "name": "TICKET/0042", "subject": "Broken widget",
        "description": "It broke", "partner": {"id": 5, "name": "Jane"},
        "owner": None, "team": {"id": 1, "name": "Support"},
        "stage": {"id": 2, "name": "In Progress"}, "priority": {"id": 1, "name": "High"},
        "category": None, "company": {"id": 1, "name": "Troc"},
        "assignees": [], "extra_fields": [{"field_name": "apple_serial", "value": "X1"}],
        "attachments": [{"id": 56, "name": "photo.png"}],
    }

@pytest.fixture
def helpdesk(monkeypatch):
    return OdooHelpdesk(
        instance="https://odoo.example/", api_key="k-123", company_id=1,
        action="create",
    )
```

---

## 5. Acceptance Criteria

- [ ] `navigator/actions/odoo_helpdesk.py` exists with `class OdooHelpdesk(AbstractTicket, RESTAction)` conforming to the real `AbstractTicket`/`RESTAction` contracts (verified in §6, not copied from a sketch).
- [ ] `create()` performs POST then GET and returns a Zammad-shaped dict containing a `number` key.
- [ ] `update()` performs PUT and adapts `{"ticket":{...}}`; passing `body` does not attempt to read a description change back.
- [ ] `get_ticket()` returns Zammad shape with top-level `subject`/`body`; sends mandatory `company_id`.
- [ ] `get_articles()` returns a synthetic single-element article list.
- [ ] `list_tickets()` adapts to `{tickets, tickets_count, assets:{Ticket:{...}}}` and drops a Zammad-only `state_id` kwarg.
- [ ] `get_attachment_img()` extracts the trailing id from a `"/12/34/56"` path and streams the binary like Zammad's version.
- [ ] `find_user()`/`create_user()` are truthy no-ops.
- [ ] `X-Helpdesk-Api-Key` header is set; no `Authorization: Bearer` header is injected.
- [ ] `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY` added to `navigator/conf.py`.
- [ ] No changes to the existing `Odoo` class or any navapi tenant view file.
- [ ] All tests pass: `pytest navigator/tests/actions/test_odoo_helpdesk.py -v`.
- [ ] Completion note lists exact file paths touched and any base-class assumption from NAV-9101 that proved wrong.

---

## 6. Codebase Contract

### Verified Imports & signatures (read in this repo, not assumed)
```python
# navigator/actions/ticket.py — AbstractTicket(AbstractAction)
#   __init__ pops _kwargs['action'] (default 'create'); abstract create(); run() dispatches 'create'.
from navigator.actions.ticket import AbstractTicket

# navigator/actions/rest.py — RESTAction
#   class attrs: auth_type='key' (line 40), token_type='Bearer' (line 41)
#   __init__ (line 44): builds self.headers (line 64); self.file_buffer = kwargs.pop('file_buffer', False) (line 57)
#   request(self, url, method='get', data=None, cookies=None, headers=None)  (line 113) → (result, error)
#       * if auth_type=='apikey': injects headers['Authorization']=f"{token_type} {auth['apikey']}" (lines 138-142)  ← DO NOT USE
#       * file_buffer branch at line 338 (streaming/raw path)
#   async_request(...) (line 404): aiohttp path; same apikey/Bearer branch (line 432); file_buffer branch (line 586)
from navigator.actions.rest import RESTAction

# navigator/actions/abstract.py — AbstractAction
#   open() (line 51), close() (line 55), __aenter__ (line 65), __aexit__ (line 69)

# navigator/exceptions.py
from navigator.exceptions import ConfigError

# navigator/conf.py — existing ZAMMAD_* block at lines 243-251 (pattern to mirror); config from navconfig
from navconfig import config
```

### Existing reference class signatures
```python
# navigator/actions/zammad.py:24  — the mirror target
class Zammad(AbstractTicket, RESTAction):
    auth_type = 'apikey'; token_type = 'Bearer'
    article_base = {"type": "note", "internal": False}; data_format = 'raw'
    def __init__(self, *args, **kwargs):                 # pops zammad_instance/zammad_token from self._kwargs
    async def list_tickets(self, **kwargs): ...          # pops state_id; returns {tickets, tickets_count, assets}
    async def update(self, ticket: int, **kwargs): ...   # method='put'; error via ConfigError
    async def create(self, **kwargs): ...                # method='post'; checks `if error is not None: raise ConfigError(error['message'])`
    async def create_user(self): ...
    async def find_user(self, search: dict = None): ...
    async def get_ticket(self, ticket_id=None): ...
    async def get_articles(self, ticket_id: int): ...
    async def get_attachment_img(self, attachment: str, request: Request): ...  # sets self.file_buffer=True; StreamResponse chunked

# navigator/actions/odoo.py:8 — DO NOT MODIFY; copy only the direct-header idiom
class Odoo(RESTAction):
    def __init__(self, *args, **kwargs):
        self.instance = self._kwargs.pop('instance', ODOO_HOST)
        self.api_key  = self._kwargs.pop('api_key', ODOO_APIKEY)
        self.headers['api-key'] = self.api_key            # ← direct header, no auth_type
```

### Consumer-side (navapi) response shapes to preserve (context only — not edited here)
```python
# apps/zammad/views.py & apps/{apple,bose,pokemon,support}/views.py
new_ticket.get("number")          # → OdooHelpdesk create() must expose 'number'
result['assets']['Ticket']        # → list_tickets() must expose assets.Ticket
# first-article subject/body merges → get_articles() synthetic single article
```

---

## 7. Implementation Notes & Constraints

- **Never set `auth_type = 'apikey'`** on `OdooHelpdesk`. Leave it at the inherited default (`'key'`) and set the API-key header manually in `__init__`, exactly like the existing `Odoo` class does with `api-key`. A test asserts no `Authorization` header appears.
- **Use `request()` (the executor/`requests` path) for create/update/get/list**, matching `Zammad`'s own usage; use `async_request()` + `self.file_buffer = True` only for `get_attachment_img`.
- **`company_id` is mandatory on every GET** — build it from `self.company_id` (kwargs/`ODOO_HELPDESK_COMPANY`). If absent when a GET is attempted, raise `ConfigError` early rather than sending a request guaranteed to 400.
- **Consume payload fields via `self._kwargs.pop(...)`** and spread the remainder into the POST/PUT body so tenant-prefixed/unknown keys (`apple_*`, `organization_id`, etc.) pass through to Odoo's extra-fields handling — mirror `Zammad.create()`.
- **Error idiom**: `result, error = await self.request(...)`; `if error is not None: raise ConfigError(f"...: {error['message']}")`. Wrap unexpected exceptions in `ConfigError(...) from e` like `Zammad`.
- **`data_format`/encoding**: match how `Zammad` serializes (`self._encoder.dumps(data)` for PUT; dict passed directly for POST) — confirm against `RESTAction.request()` body handling during implementation and follow whichever path `Zammad` uses successfully today.
- Keep the `get_attachment_img` streaming machinery (chunked `StreamResponse`, `Content-Range`) identical to `Zammad`'s, but relax the hard `image/`-only content-type check — Odoo attachments legitimately include PDFs/docs (see §8 Q2).

## Worktree Strategy

Implementation happens in **this repo** (`navigator`), on branch `NAV-9101-odoo-helpdesk-action` (already created off `master`). Per `sdd/WORKFLOW.md`, decompose with `/sdd-task` and implement via `/sdd-start`. Single-feature scope (one new file + conf + tests) — a dedicated worktree is optional; working directly on the `NAV-9101-*` branch is acceptable.

The navapi repo holds a mirror of the brainstorm/spec for tracking; **no code changes land in navapi** under this ticket.

---

## 8. Open Questions

| # | Question | Disposition |
|---|---|---|
| Q1 | `number` mapping: Zammad `number` is a numeric-ish string; Odoo `name` is a sequence like `"TICKET/0042"`. Should `number` expose Odoo `name` (human reference) or the numeric `ticket_id`? | **Decided (default)**: `number` = Odoo `name`; numeric id also exposed as `id`. Callers only `.get("number")` for display. Flag to reviewer; cheap to change if a tenant frontend parses `number` numerically. |
| Q2 | `get_attachment_img` currently hard-fails on non-`image/` content types (Zammad behavior). Odoo attachments include PDFs/docs. | **Decided (deviation)**: relax to accept any content type; preserve streaming mechanics. Flagged per NAV-9101 non-goal ("flag discrepancies rather than guess"). |
| Q3 | Per-tenant `ODOO_<TENANT>_*` settings: ticket says add to `navigator/conf.py`, but the existing per-tenant `ZAMMAD_<TENANT>_*` pattern lives in **navapi** `settings/settings.py`. | **Decided**: only generic `ODOO_HELPDESK_*` go in `conf.py` (this repo); per-tenant values are added to navapi `settings/settings.py` during the later tenant-migration ticket. Documented as a NAV-9101 correction. |
| Q4 | Webhook contract finality (§2 table) — untested against a live instance in this ticket. | Coded to the documented contract; any mismatch found later is a follow-up correction, not silently patched. |

---

## Revision History
| Date | Author | Change |
|---|---|---|
| 2026-07-09 | Claude | Initial draft from brainstorm `odoo-helpdesk-action` (NAV-9101 / G10). |
