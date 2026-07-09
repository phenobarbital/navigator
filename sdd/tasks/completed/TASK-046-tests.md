# TASK-046: Unit tests for OdooHelpdesk (HTTP layer mocked)

**Feature**: FEAT-006 — OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)
**Spec**: `sdd/specs/odoo-helpdesk-action.spec.md`
**Jira**: NAV-9101
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-042, TASK-043, TASK-044, TASK-045
**Assigned-to**: unassigned

---

## Context

Final task (Spec §3 Module 3, §4). Covers all 6 test areas required by NAV-9101 with the HTTP layer mocked — no live Odoo instance. Patch `OdooHelpdesk.request` / `OdooHelpdesk.async_request` so tests assert on the outgoing URL/method/body and the adapted return shape.

---

## Scope

Create `navigator/tests/actions/test_odoo_helpdesk.py` (create the `navigator/tests/actions/` package dir + `__init__.py` if absent). Implement the tests in the Spec §4 table:

| Test | Verifies |
|---|---|
| `test_create_builds_post_payload_and_adapts` | POST body keys + POST→GET two-step; return has `number == odoo name`, `id == ticket_id`. |
| `test_create_two_step_post_then_get` | Exactly 2 calls: POST `helpdesk/ticket`, then GET `helpdesk/ticket/<id>` with `company_id`. |
| `test_create_raises_on_error` | `request` returns `(None, {"message": "..."})` → `ConfigError` with the message. |
| `test_update_sends_put_and_adapts` | PUT to `helpdesk/ticket/<id>`; adapts `{"ticket":{...}}`. |
| `test_update_with_body_no_description_readback` | `body` in payload → no description read-back from response. |
| `test_list_tickets_adapts_shape` | `{count,limit,offset,tickets}` → `{tickets, tickets_count, assets:{Ticket:{<id>:{...}}}}`. |
| `test_list_tickets_drops_state_id` | `state_id` kwarg absent from outgoing query string. |
| `test_get_ticket_top_level_subject_body` | top-level `subject`/`body`; mandatory `company_id`, optional `as_user`. |
| `test_get_articles_synthetic_single` | 1-element list from `get_ticket()`. |
| `test_get_attachment_img_parses_trailing_id` | `_parse_attachment_path("/12/34/56") == "56"`; GET hits `helpdesk/attachment/56`. |
| `test_find_user_and_create_user_are_truthy_noops` | both truthy, no HTTP call. |
| `test_api_key_header_set_no_bearer` | `X-Helpdesk-Api-Key` set; no `Authorization` header. |

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/tests/actions/__init__.py` | CREATE (if absent) | package marker |
| `navigator/tests/actions/test_odoo_helpdesk.py` | CREATE | the test module |

---

## Codebase Contract (Anti-Hallucination)

### Test approach
```python
from unittest.mock import AsyncMock, patch
import pytest
from navigator.actions.odoo_helpdesk import OdooHelpdesk

# request() returns (result, error). Patch it to feed canned responses and capture call args.
# For create(): side_effect=[(post_result, None), (get_result, None)] to model POST then GET.
```

### Fixtures (Spec §4)
- `odoo_ticket_record` — a full Odoo ticket dict (id 42, name "TICKET/0042", nested partner/team/stage/priority, extra_fields, attachments).
- `helpdesk` — `OdooHelpdesk(instance="https://odoo.example/", api_key="k-123", company_id=1, action="create")`.

### Verified facts
- `request(self, url, method='get', data=None, ...)` → `(result, error)`; error dict carries `message`.
- `auth_type` default is `'key'` (rest.py:40) — test asserts it is NOT `'apikey'` and no `Authorization` header present.

---

## Implementation Notes

- Mark async tests with `@pytest.mark.asyncio` (the repo uses `pytest-asyncio`).
- Assert on **captured call args** of the patched `request` (URL contains `company_id`, method is `post`/`put`/`get`, body dict has expected keys) — not just on return values.
- For `test_api_key_header_set_no_bearer`: construct the instance and inspect `helpdesk.headers` directly; assert `'X-Helpdesk-Api-Key' in headers` and `'Authorization' not in headers`.
- For attachment streaming, mocking the full `StreamResponse` write loop is heavy — assert the parsed id + outgoing URL rather than the streamed bytes.

---

## Acceptance Criteria

- [ ] All 12 tests present and passing: `source .venv/bin/activate && pytest navigator/tests/actions/test_odoo_helpdesk.py -v`
- [ ] Tests mock the HTTP layer — no network calls, no live Odoo.
- [ ] The `no Authorization / X-Helpdesk-Api-Key present` assertion passes (regression guard for the `auth_type` trap).
- [ ] `state_id`-dropped assertion inspects the actual outgoing query string.

---

## Agent Instructions

1. Confirm TASK-042…045 are all in `sdd/tasks/completed/`.
2. Read Spec §4 and the final `odoo_helpdesk.py`.
3. Implement the tests; run them with venv activated.
4. On completion, move this file to `sdd/tasks/completed/`, fill the Completion Note, and (per Spec §5) record the exact file paths touched across FEAT-006 plus any NAV-9101 base-class assumption that proved wrong.

---

## Completion Note

Added `tests/actions/test_odoo_helpdesk.py` (+ `tests/actions/__init__.py`) with **13 tests** covering all 6 NAV-9101 areas. HTTP layer mocked via `unittest.mock.AsyncMock` on `OdooHelpdesk.request`; `StreamResponse` patched for the attachment test. Result:

```
$ PYTHONPATH=<navigator> python -m pytest tests/actions/test_odoo_helpdesk.py -v --noconftest
13 passed in 4.95s
```

(`--noconftest` avoids the repo-root `tests/conftest.py`, which imports `trustme` for unrelated SSL fixtures not installed here; `asyncio_mode = auto` from `pytest.ini` runs the `async def` tests without a marker.)

---

## FEAT-006 — final summary (NAV-9101 AC)

**Exact file paths touched (all in the `navigator` framework repo):**
- `navigator/conf.py` — added `ODOO_HELPDESK_INSTANCE/API_KEY/COMPANY`.
- `navigator/actions/odoo_helpdesk.py` (NEW) — `class OdooHelpdesk(AbstractTicket, RESTAction)` with `create`, `update`, `get_ticket`, `list_tickets`, `get_articles`, `get_attachment_img`, `find_user`, `create_user` + helpers `_company_qs`, `_to_zammad_ticket`, `_parse_attachment_path`, `_ticket_payload`.
- `tests/actions/__init__.py` (NEW), `tests/actions/test_odoo_helpdesk.py` (NEW).
- SDD artifacts: `sdd/proposals/odoo-helpdesk-action.brainstorm.md`, `sdd/specs/odoo-helpdesk-action.spec.md`, `sdd/tasks/{active,completed}/TASK-042..046-*.md`.
- Untouched (verified): the existing `Odoo` class in `navigator/actions/odoo.py`; all navapi tenant view files.

**NAV-9101 assumptions that proved wrong / needed correcting (for the next reader):**
1. **Settings location** — the ticket said to add per-tenant `ODOO_<TENANT>_*` to `navigator/conf.py`. Wrong: the existing per-tenant `ZAMMAD_<TENANT>_*` pattern lives in the **navapi** consumer's `settings/settings.py`, not the framework `conf.py`. Only the generic `ODOO_HELPDESK_*` were added here; per-tenant values are deferred to the navapi-side migration ticket.
2. **Test path** — the ticket said `navigator/tests/actions/test_odoo_helpdesk.py`. Wrong: this repo's tests live at repo-root `tests/`, so they landed at `tests/actions/test_odoo_helpdesk.py`.
3. **`RESTAction.request()` POST vs PUT serialization asymmetry** (not stated in the ticket, discovered by reading `rest.py`): POST auto-`dumps` the `data` (pass a dict), but PUT does **not** (must pre-`dumps`). Mirrors `Zammad.create`/`Zammad.update`.
4. **Deliberate deviations from Zammad in `get_attachment_img`** (spec §8 Q2): dropped the `image/*`-only guard and hard filename requirement — Odoo attachments include PDFs/docs; added a graceful `attachment_<id>` filename fallback.
5. **`number` mapping** (spec §8 Q1): exposed as the Odoo sequence `name` (e.g. `"TICKET/0042"`), with the numeric id also available under `id`.

**Deployment caveat (flagged earlier, still open):** navapi's venv has `navigator` installed as a **copied** package in `site-packages`, not editable — the running app will not see `odoo_helpdesk.py` until `navigator` is reinstalled/rebuilt in navapi's env. All verification here used the source repo on `PYTHONPATH`. `pytest`/`pytest-asyncio` were installed into navapi's venv to run these tests (they were absent).
