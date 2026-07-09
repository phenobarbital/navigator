# TASK-045: Implement get_articles(), get_attachment_img(), find_user()/create_user()

**Feature**: FEAT-006 — OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)
**Spec**: `sdd/specs/odoo-helpdesk-action.spec.md`
**Jira**: NAV-9101
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-042, TASK-043
**Assigned-to**: unassigned

---

## Context

Completes the method surface (Spec §2, §3 Module 1). Odoo has no "article" concept, so `get_articles()` synthesizes a single-element list from `get_ticket()` (hence the dependency on TASK-043). `get_attachment_img()` streams a binary from a new Odoo endpoint but is driven by a Zammad-style path argument. `find_user()`/`create_user()` become truthy no-ops because Odoo auto-creates the partner from `customer` — so existing `if not result: await user.create_user()` branches in tenant views never fire after migration.

---

## Scope

1. **`async def get_articles(self, ticket_id)`**:
   - Call `z = await self.get_ticket(ticket_id)`.
   - Return a **single-element** list: `[{"id": ticket_id, "subject": z["subject"], "body": z["body"], "attachments": z.get("attachments", [])}]`.

2. **`async def get_attachment_img(self, attachment: str, request: Request, user=None)`**:
   - `att_id = self._parse_attachment_path(attachment)` (Zammad passes a path like `"/{ticket}/{article}/{attachment}"`).
   - `GET {instance}helpdesk/attachment/<att_id>` + `self._company_qs({'as_user': user} if user else None)`.
   - `self.file_buffer = True`; use the streaming path (mirror `Zammad.get_attachment_img`, zammad.py:383-466: `StreamResponse`, chunked write, `Content-Range`, `Content-Disposition` filename parsing).
   - **Deviation (Spec §8 Q2)**: do NOT hard-fail on non-`image/` content types — Odoo attachments include PDFs/docs. Use the response's `Content-Type` as-is (default `application/octet-stream`).

3. **`async def find_user(self, search=None)`** and **`async def create_user(self)`**:
   - Truthy no-ops. Return a small truthy sentinel (e.g. `{"noop": True}`) without any HTTP call, so `if not result: await user.create_user()` never fires.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/actions/odoo_helpdesk.py` | MODIFY | add `get_articles()`, `get_attachment_img()`, `find_user()`, `create_user()` |

---

## Codebase Contract (Anti-Hallucination)

### Reference to mirror
```python
# navigator/actions/zammad.py:383-466 — get_attachment_img streaming machinery to reuse:
#   self.file_buffer = True
#   result, error = await self.request(self.url, 'get')   # returns (image, response) tuple when file_buffer
#   image, response = result
#   content_type = response.headers.get('Content-Type', 'application/octet-stream')
#   content_disposition → filename; StreamResponse(status=200, headers={...}); chunked write loop.
```

### Contract facts (Spec §2 table)
- `GET helpdesk/attachment/<id>?company_id=&as_user=` streams raw binary with `Content-Type`/`Content-Disposition`/`Content-Length`; same company_id/not_found/forbidden error pattern.

### DECIDED deviations
- Spec §8 Q2: relax the Zammad `image/`-only guard (accept any content type). Keep streaming mechanics identical.

---

## Implementation Notes

- `get_attachment_img` uses `async_request()`/`file_buffer` semantics exactly as `Zammad` does (whichever call Zammad uses for the streaming path); confirm against `rest.py` file_buffer branches (rest.py:338 / 586).
- Keep the chunked-write + `StreamResponse` block byte-for-byte compatible with Zammad's so tenant frontends behave identically.
- No-ops must be genuinely truthy and side-effect-free (no network) — a dict/`True` is fine.

---

## Acceptance Criteria

- [ ] `get_articles()` returns a 1-element list with `id`/`subject`/`body`/`attachments`, sourced from `get_ticket()`.
- [ ] `get_attachment_img("/12/34/56", request)` GETs `helpdesk/attachment/56`.
- [ ] `get_attachment_img()` streams non-image content types without raising (PDF/doc allowed).
- [ ] `find_user()` and `create_user()` return truthy values and make no HTTP call.

---

## Agent Instructions

1. Confirm TASK-042 and TASK-043 are in `sdd/tasks/completed/`.
2. Read Spec §2 and `Zammad.get_articles`/`get_attachment_img`.
3. Implement per scope; tests are TASK-046.
4. On completion, move this file to `sdd/tasks/completed/` and fill the Completion Note.

---

## Completion Note
(fill on completion)
