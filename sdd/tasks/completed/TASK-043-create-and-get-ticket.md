# TASK-043: Implement create() + get_ticket()

**Feature**: FEAT-006 — OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)
**Spec**: `sdd/specs/odoo-helpdesk-action.spec.md`
**Jira**: NAV-9101
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-042
**Assigned-to**: unassigned

---

## Context

Implements the core write+read path (Spec §2, §3 Module 1). `create()` is the method every tenant view calls first (`await ticket.create(**res)`), and it drives the two-step POST→GET dance because the Odoo `POST helpdesk/ticket` response is flat (`{ok, ticket_id, ticket_name}`) and has no full record — a follow-up GET builds the Zammad-shaped dict. `get_ticket()` is implemented here because `create()` reuses it.

---

## Scope

1. **`async def get_ticket(self, ticket_id, user=None)`**:
   - `GET {instance}helpdesk/ticket/<ticket_id>` + `self._company_qs({'as_user': user} if user else None)`.
   - `result, error = await self.request(self.url, 'get')`; on `error is not None` raise `ConfigError(f"...: {error['message']}")`.
   - Return `self._to_zammad_ticket(result['ticket'])` — top-level `subject`/`body`, no article wrapping.

2. **`async def create(self, **kwargs)`** (replace the TASK-042 stub):
   - `POST {instance}helpdesk/ticket`. Build a **flat** body: pop the mapped keys from `self._kwargs` (`title`/`subject`, `body`, `customer`, `firstname`/`lastname`, `owner`, `group`, `type`, `state`/`state_name`, `priority`/`priority_id`, `contact_name`, `organization_id`, `attachments`) and spread the remainder so tenant-prefixed/unknown keys pass through to Odoo extra-fields (mirror `Zammad.create` field consumption, zammad.py:206-249).
   - `result, error = await self.request(self.url, 'post', data=...)`; on error raise `ConfigError`.
   - Take `ticket_id = result['ticket_id']`; call `await self.get_ticket(ticket_id, user=<owner/as_user if applicable>)`.
   - Return the Zammad-shaped dict (already contains `number` via `_to_zammad_ticket`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/actions/odoo_helpdesk.py` | MODIFY | add `get_ticket()`, implement `create()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified signatures
```python
# navigator/actions/rest.py
async def request(self, url, method='get', data=None, cookies=None, headers=None): ...  # → (result, error)
#   error is None on success; on failure error is a dict with a 'message' key.

# navigator/actions/zammad.py:250-259 — the exact error-check idiom to mirror
result, error = await self.request(self.url, self.method, data=data)
if error is not None:
    raise ConfigError(f"Error creating Zammad Ticket: {error['message']}")
```

### Contract facts (Spec §2 table)
- POST success 200: `{"ok": true, "ticket_id": <int>, "ticket_name": "<subject>"}` — flat.
- GET requires `company_id` (missing→400, mismatch→404); optional `as_user`.
- GET success: `{"ticket": {id, name, subject, description, partner, owner, team, stage, priority, category, company, assignees, extra_fields, attachments}}`.
- `body` on POST writes description (create only) — do not resend it on the follow-up GET.

---

## Implementation Notes

- Use `self.request()` (the executor path), NOT `async_request()` — matches `Zammad`'s own create/get usage.
- Serialization: match how `Zammad.create()` passes `data` (dict passed directly to `request()` for POST; `Zammad.update()` uses `self._encoder.dumps(data)` for PUT). Confirm against `RESTAction.request()` body handling; follow the path `Zammad` uses successfully.
- `number` mapping is decided in Spec §8 Q1: `number = odoo['name']` (e.g. `"TICKET/0042"`). Do not coerce to int.
- If `owner`/`as_user` is relevant for the follow-up GET impersonation, thread it through; otherwise GET as the api-key principal.

---

## Acceptance Criteria

- [ ] `create()` issues exactly one POST then one GET (to `helpdesk/ticket/<ticket_id>` with `company_id`).
- [ ] `create()` returns a Zammad-shaped dict where `.get("number")` is truthy and equals the Odoo `name`.
- [ ] `create()` raises `ConfigError` carrying `error['message']` when the POST errors.
- [ ] `get_ticket()` returns top-level `subject`/`body`; sends mandatory `company_id`.
- [ ] Unknown/tenant-prefixed kwargs (e.g. `apple_serial`, `organization_id`) are included in the POST body, not dropped.

---

## Agent Instructions

1. Confirm TASK-042 is in `sdd/tasks/completed/`.
2. Read Spec §2 (contract + adapter) and `Zammad.create`/`Zammad.get_ticket`.
3. Implement per scope; keep tests for TASK-046.
4. On completion, move this file to `sdd/tasks/completed/` and fill the Completion Note.

---

## Completion Note

Implemented `get_ticket()` and `create()` in `navigator/actions/odoo_helpdesk.py` (+ a private `_ticket_payload()` helper and a `_control_keys` tuple).

**Design refinement vs. the task's literal "pop each mapped key" wording:** the Odoo webhook maps standard keys to native fields and routes tenant-prefixed/unknown keys to extra fields **server-side**. So the faithful drop-in is to forward the caller payload **flat** after stripping only adapter-level control keys (`instance`, `api_key`, `company_id`, `as_user`, `action`) via `_ticket_payload()` — rather than re-mapping fields the server already maps. This is more correct (no double-mapping) and matches Spec §2 ("Standard keys map to native fields... tenant-prefixed keys land in extra fields").

**Confirmed against `rest.py` (the task's "confirm before using" item):**
- `RESTAction.request()` for **POST** with `data_format='raw'` (inherited default) does `self._encoder.dumps(data)` internally (rest.py:231) → pass a **dict**, exactly like `Zammad.create`. Do NOT pre-dump for POST.
- **PUT** (rest.py:238-242) does NOT dump → the caller must pre-dump (relevant to TASK-044, matching `Zammad.update`).
- **GET** passes `data` as `params` (rest.py:216-221); this impl puts the query string directly in the URL instead, so `request(url, 'get')` is called with `data=None`.
- On success with `accept='application/json'`, `result = self._encoder.loads(response.text)` (rest.py:414) → a parsed **dict**, so `result['ticket_id']` / `result['ticket']` are valid.
- HTTP errors **raise** `ConfigError` from inside `request()` (rest.py:299/312); the `if error is not None` check is defensive. `create()`/`get_ticket()` mirror `Zammad`'s dual guard (check `error` + wrap in try/except).

**Verification (runtime, `request` mocked):** POST→GET two-step in order; POST hits `helpdesk/ticket`, follow-up GET hits `helpdesk/ticket/42?company_id=1`; POST body forwards app fields (`title`, `apple_serial`) and strips control keys; return is Zammad-shaped with `number=="TICKET/0042"`, `id==42`, flattened `customer`/`state`; `get_ticket(42, user="agentB")` overrides instance `as_user`; error path raises `ConfigError` carrying the webhook `message`.

**Files touched:** `navigator/actions/odoo_helpdesk.py` (added `_ticket_payload`, `get_ticket`, `create`; replaced the TASK-042 stub).

**No NAV-9101 base-class assumption proved wrong** for this task — the `RESTAction` POST/PUT dump asymmetry is the one non-obvious fact, now documented above and carried into TASK-044.

**Type-checker note:** pyright flags `result['ticket']` etc. because `RESTAction.request()` is untyped (infers a `Path|None` union); runtime is correct and `zammad.py` has the same pattern. Left as-is to match house style.
