# TASK-044: Implement update() + list_tickets()

**Feature**: FEAT-006 — OdooHelpdesk Action Class (Zammad→Odoo drop-in, NAV-9101 / G10)
**Spec**: `sdd/specs/odoo-helpdesk-action.spec.md`
**Jira**: NAV-9101
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-042
**Assigned-to**: unassigned

---

## Context

Implements the update path and the list path (Spec §2, §3 Module 1). Independent of TASK-043 — both only need the TASK-042 helpers, so this can proceed in parallel with 043. `update()` maps `body` to an internal chatter note server-side (not description), so the adapter must NOT try to read a description change back. `list_tickets()` reshapes Odoo's `{count, limit, offset, tickets}` into Zammad's `{tickets, tickets_count, assets:{Ticket:{...}}}` and drops the Zammad-only `state_id` kwarg.

---

## Scope

1. **`async def update(self, ticket: int, **kwargs)`**:
   - `PUT {instance}helpdesk/ticket/<ticket>`. Build the body with the same key semantics as `create()` (pop mapped keys, spread remainder). `body` is allowed and becomes a chatter note server-side.
   - `result, error = await self.request(self.url, 'put', data=...)`; on error raise `ConfigError`.
   - PUT success is `{"ticket": {...full...}}` → return `self._to_zammad_ticket(result['ticket'])`. Do NOT assert/read a description change from the response.

2. **`async def list_tickets(self, user=None, **kwargs)`**:
   - **Drop** any `state_id` kwarg (Zammad-only) — `kwargs.pop('state_id', None)`; do not forward it.
   - Map remaining supported filters to the Odoo query: `team_id`, `stage_id`, `limit`, `offset`, plus mandatory `company_id` and optional `as_user` (from `user`).
   - `GET {instance}helpdesk/tickets?<qs>`; on error raise `ConfigError`.
   - Adapt `{count, limit, offset, tickets:[...]}` →
     ```python
     {
       "tickets": [...],                 # mirror what Zammad callers iterate
       "tickets_count": result["count"],
       "assets": {"Ticket": {str(t["id"]): self._to_zammad_ticket(t) for t in result["tickets"]}},
     }
     ```

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator/actions/odoo_helpdesk.py` | MODIFY | add `update()`, `list_tickets()` |

---

## Codebase Contract (Anti-Hallucination)

### Reference behavior to mirror / diverge from
```python
# navigator/actions/zammad.py:78-143 — list_tickets: note it pops state_id (line 84) and returns
#   {"tickets", "tickets_count", "assets"} — SAME output keys OdooHelpdesk must produce.
# navigator/actions/zammad.py:145-191 — update: method='put'; body via self._encoder.dumps(data).
```

### Contract facts (Spec §2 table)
- PUT success: `{"ticket": {...serialized...}}`; `body` → internal note (create-only writes description).
- GET tickets success: `{"count": N, "limit": L, "offset": O, "tickets": [<single-ticket shape>...]}`, id desc; `limit` default 80, cap 200; `company_id` mandatory.

---

## Implementation Notes

- Use `self.request()` (executor path), matching `Zammad`. For PUT, serialize `data` the way `Zammad.update()` does (`self._encoder.dumps(data)`); confirm against `RESTAction.request()`.
- `list_tickets` "tickets" list: match whatever concrete shape existing Zammad callers iterate over in navapi (`result['assets']['Ticket']` is the primary access path; keep `tickets` as the list Zammad returns). When in doubt, keep both populated as in Zammad's own return.
- Reuse `_company_qs()` and `_to_zammad_ticket()` from TASK-042.

---

## Acceptance Criteria

- [ ] `update()` issues a PUT to `helpdesk/ticket/<id>` and returns a `_to_zammad_ticket`-shaped dict.
- [ ] `update()` with a `body` kwarg does not attempt to read a description change from the response.
- [ ] `list_tickets()` returns `{tickets, tickets_count, assets:{Ticket:{<id>:{...}}}}`.
- [ ] `list_tickets(state_id=[1,2,3])` does NOT include `state_id` in the outgoing query string.
- [ ] `list_tickets()` sends mandatory `company_id`.

---

## Agent Instructions

1. Confirm TASK-042 is in `sdd/tasks/completed/`.
2. Read Spec §2 and `Zammad.update`/`Zammad.list_tickets`.
3. Implement per scope; tests are TASK-046.
4. On completion, move this file to `sdd/tasks/completed/` and fill the Completion Note.

---

## Completion Note
(fill on completion)
