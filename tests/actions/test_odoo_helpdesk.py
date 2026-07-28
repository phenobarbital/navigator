"""Unit tests for the ``OdooHelpdesk`` action (FEAT-006, NAV-9101 / G10).

The HTTP layer (:meth:`RESTAction.request`) is mocked throughout -- these tests
never touch a live Odoo instance. They assert both on the *outgoing* call
(URL / method / body) and on the adapted, Zammad-shaped return values, covering
the six areas required by NAV-9101:

1. ``create()`` POST payload + POST->GET adaptation with a ``number`` key.
2. ``update()`` PUT + adaptation, including ``body`` (no description read-back).
3. ``list_tickets()`` shape adaptation + ``state_id`` dropped.
4. ``get_attachment_img()`` trailing-id extraction from a Zammad-style path.
5. ``find_user()`` / ``create_user()`` truthy no-ops.
6. API key sent as ``Authorization: Bearer`` (Odoo native API key).

Note: the repo's ``pytest.ini`` sets ``asyncio_mode = auto`` so ``async def``
tests run without an explicit marker.
"""
from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from navigator.actions.odoo_helpdesk import OdooHelpdesk


# --------------------------------------------------------------------------- #
# Fixtures & helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def odoo_ticket_record() -> dict:
    """A fully serialized Odoo Helpdesk ticket record (GET shape)."""
    return {
        "id": 42,
        "name": "TICKET/0042",
        "subject": "Broken widget",
        "description": "It broke",
        "partner": {"id": 5, "name": "Jane"},
        "owner": None,
        "team": {"id": 1, "name": "Support"},
        "stage": {"id": 2, "name": "In Progress"},
        "priority": {"id": 1, "name": "High"},
        "category": None,
        "company": {"id": 1, "name": "Troc"},
        "assignees": [],
        "extra_fields": [{"field_name": "apple_serial", "value": "X1"}],
        "attachments": [{"id": 56, "name": "photo.png"}],
    }


def make_helpdesk(**overrides) -> OdooHelpdesk:
    """Build an ``OdooHelpdesk`` with sensible test defaults."""
    kwargs = {
        "instance": "https://odoo.example/",
        "api_key": "k-123",
        "company_id": 1,
        "action": "create",
    }
    kwargs.update(overrides)
    return OdooHelpdesk(**kwargs)


class _FakeResponse:
    """Minimal stand-in for an aiohttp/requests response (attachment path)."""

    def __init__(self, headers: dict):
        self.headers = headers


class _FakeStream:
    """Stand-in for ``aiohttp.web.StreamResponse`` capturing the stream."""

    def __init__(self, status: int = 200, headers: dict = None):
        self.status = status
        self.headers = dict(headers or {})
        self.written = b""
        self.prepared = False

    async def prepare(self, request):
        self.prepared = True

    async def write(self, chunk):
        self.written += chunk

    async def drain(self):
        pass

    async def write_eof(self):
        pass


# --------------------------------------------------------------------------- #
# 6. Header wiring — Odoo native API key via Authorization: Bearer
# --------------------------------------------------------------------------- #
def test_api_key_sent_as_bearer():
    hd = make_helpdesk()
    assert hd.headers.get("Authorization") == "Bearer k-123"
    # legacy X-Helpdesk-Api-Key header must not be used anymore
    assert "X-Helpdesk-Api-Key" not in hd.headers


# --------------------------------------------------------------------------- #
# 1. create()
# --------------------------------------------------------------------------- #
async def test_create_builds_post_payload_and_adapts(odoo_ticket_record):
    post_result = {"ok": True, "ticket_id": 42, "ticket_name": "Broken widget"}
    request = AsyncMock(side_effect=[(post_result, None), ({"ticket": odoo_ticket_record}, None)])
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.create(
            title="Broken widget",
            customer="jane@example.com",
            apple_serial="X1",
            # control keys that must be stripped from the body:
            instance="https://odoo.example/",
            api_key="k-123",
            company_id=1,
        )

    # POST body forwards app fields, strips adapter-control keys
    post_call = request.call_args_list[0]
    body = post_call.kwargs["data"]
    assert body["title"] == "Broken widget"
    assert body["apple_serial"] == "X1"
    for control in ("instance", "api_key", "company_id", "action"):
        assert control not in body

    # Adapted, Zammad-shaped result with a `number` key
    assert result["number"] == "TICKET/0042"
    assert result["id"] == 42
    assert result["subject"] == "Broken widget"
    assert result["body"] == "It broke"
    assert result["customer"] == "Jane"
    assert result["state"] == "In Progress"


async def test_create_two_step_post_then_get(odoo_ticket_record):
    post_result = {"ok": True, "ticket_id": 42, "ticket_name": "Broken widget"}
    request = AsyncMock(side_effect=[(post_result, None), ({"ticket": odoo_ticket_record}, None)])
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        await hd.create(title="Broken widget")

    assert request.call_count == 2
    post_call, get_call = request.call_args_list
    assert post_call.args[0] == "https://odoo.example/helpdesk/ticket"
    assert post_call.args[1] == "post"
    assert get_call.args[0] == "https://odoo.example/helpdesk/ticket/42?company_id=1"
    assert get_call.args[1] == "get"


async def test_create_uses_post_ticket_when_present(odoo_ticket_record):
    # Newer webhook returns the full ticket in the POST response -> no follow-up GET.
    post_result = {
        "ok": True, "ticket_id": 42, "ticket_name": "Broken widget",
        "ticket": odoo_ticket_record,
    }
    request = AsyncMock(return_value=(post_result, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.create(title="Broken widget")

    assert request.call_count == 1  # POST only, no follow-up GET
    assert result["number"] == "TICKET/0042"
    assert result["id"] == 42
    assert result["subject"] == "Broken widget"


async def test_create_raises_on_error():
    from navigator.exceptions import ConfigError

    request = AsyncMock(return_value=(None, {"message": "bad_request"}))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        with pytest.raises(ConfigError) as exc:
            await hd.create(title="x")
    assert "bad_request" in str(exc.value)


# --------------------------------------------------------------------------- #
# 2. update()
# --------------------------------------------------------------------------- #
async def test_update_sends_put_and_adapts(odoo_ticket_record):
    request = AsyncMock(return_value=({"ticket": odoo_ticket_record}, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.update(42, title="new title")

    call = request.call_args
    assert call.args[0] == "https://odoo.example/helpdesk/ticket/42"
    assert call.args[1] == "put"
    assert result["number"] == "TICKET/0042"
    assert result["subject"] == "Broken widget"


async def test_update_with_body_no_description_readback(odoo_ticket_record):
    # The PUT response deliberately has a DIFFERENT description than the `body`
    # we sent; the adapter must simply reflect the response, never try to
    # reconcile `body` (which is a chatter note server-side) with description.
    request = AsyncMock(return_value=({"ticket": odoo_ticket_record}, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.update(42, body="an internal note")

    # PUT body is a *pre-serialized* string (RESTAction.request does not dump PUT)
    data = request.call_args.kwargs["data"]
    assert isinstance(data, (str, bytes))
    body_str = data.decode() if isinstance(data, bytes) else data
    assert "an internal note" in body_str
    assert "api_key" not in body_str  # control key stripped
    # Response description is surfaced as-is; no read-back of the sent `body`.
    assert result["body"] == "It broke"


# --------------------------------------------------------------------------- #
# 3. list_tickets()
# --------------------------------------------------------------------------- #
async def test_list_tickets_adapts_shape(odoo_ticket_record):
    second = {"id": 7, "name": "TICKET/0007", "subject": "S2",
              "description": "B2", "stage": {"id": 1, "name": "New"}}
    payload = {"count": 2, "limit": 80, "offset": 0,
               "tickets": [odoo_ticket_record, second]}
    request = AsyncMock(return_value=(payload, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.list_tickets()

    assert result["tickets_count"] == 2
    assert set(result["assets"]["Ticket"].keys()) == {"42", "7"}
    assert result["assets"]["Ticket"]["42"]["number"] == "TICKET/0042"
    assert result["assets"]["Ticket"]["7"]["state"] == "New"


async def test_list_tickets_drops_state_id():
    payload = {"count": 0, "limit": 80, "offset": 0, "tickets": []}
    request = AsyncMock(return_value=(payload, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        await hd.list_tickets(state_id=[1, 2, 3], team_id=5, limit=10)

    url = request.call_args.args[0]
    assert "company_id=1" in url
    assert "team_id=5" in url
    assert "limit=10" in url
    assert "state_id" not in url  # Zammad-only kwarg must be dropped


async def test_list_tickets_forwards_filters():
    """stage/category/partner/date filters reach the webhook query string;
    unknown kwargs are dropped (NAV-9101 filters/listing)."""
    from urllib.parse import parse_qs, urlparse

    payload = {"count": 0, "limit": 80, "offset": 0, "tickets": []}
    request = AsyncMock(return_value=(payload, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        await hd.list_tickets(
            stage_name="Assigned",
            category="Hardware",
            partner_email="a@b.com",
            date_from="2026-07-01",
            date_to="2026-07-28",
            bogus_filter="drop-me",  # unknown -> must not be forwarded
        )

    url = request.call_args.args[0]
    qs = parse_qs(urlparse(url).query)
    assert qs["stage_name"] == ["Assigned"]
    assert qs["category"] == ["Hardware"]
    assert qs["partner_email"] == ["a@b.com"]
    assert qs["date_from"] == ["2026-07-01"]
    assert qs["date_to"] == ["2026-07-28"]
    assert "bogus_filter" not in qs  # only LIST_QUERY_PARAMS are forwarded


async def test_list_tickets_surfaces_warnings():
    """A non-fatal webhook `warnings` (e.g. unknown stage_name) is passed
    through; absent warnings add no key."""
    payload = {"count": 0, "limit": 80, "offset": 0, "tickets": [],
               "warnings": ["unknown stage_name 'Nope'"]}
    request = AsyncMock(return_value=(payload, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        result = await hd.list_tickets(stage_name="Nope")
    assert result["warnings"] == ["unknown stage_name 'Nope'"]

    # No warnings in the webhook response -> no warnings key in the result.
    request2 = AsyncMock(return_value=(
        {"count": 0, "limit": 80, "offset": 0, "tickets": []}, None))
    with patch.object(OdooHelpdesk, "request", request2):
        hd2 = make_helpdesk()
        result2 = await hd2.list_tickets()
    assert "warnings" not in result2


# --------------------------------------------------------------------------- #
# get_ticket() / get_articles()
# --------------------------------------------------------------------------- #
async def test_get_ticket_top_level_subject_body(odoo_ticket_record):
    request = AsyncMock(return_value=({"ticket": odoo_ticket_record}, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk(as_user="agentA")
        result = await hd.get_ticket(42, user="agentB")

    url = request.call_args.args[0]
    assert url.startswith("https://odoo.example/helpdesk/ticket/42?")
    assert "company_id=1" in url
    assert "as_user=agentB" in url  # per-call user overrides instance as_user
    assert result["subject"] == "Broken widget"
    assert result["body"] == "It broke"


async def test_get_articles_synthetic_single(odoo_ticket_record):
    request = AsyncMock(return_value=({"ticket": odoo_ticket_record}, None))
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        articles = await hd.get_articles(42)

    assert isinstance(articles, list) and len(articles) == 1
    art = articles[0]
    assert art["id"] == 42
    assert art["subject"] == "Broken widget"
    assert art["body"] == "It broke"
    assert art["attachments"] == [{"id": 56, "name": "photo.png"}]


# --------------------------------------------------------------------------- #
# 4. get_attachment_img()
# --------------------------------------------------------------------------- #
async def test_get_attachment_img_parses_trailing_id():
    response = _FakeResponse({
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="doc.pdf"',
    })
    request = AsyncMock(return_value=((BytesIO(b"PDFDATA" * 5000), response), None))
    with patch.object(OdooHelpdesk, "request", request), \
         patch("navigator.actions.odoo_helpdesk.StreamResponse", _FakeStream):
        hd = make_helpdesk()
        stream = await hd.get_attachment_img("/12/34/56", request=object())

    # Trailing id extracted; company_id present
    assert request.call_args.args[0] == \
        "https://odoo.example/helpdesk/attachment/56?company_id=1"
    # Non-image content type is accepted (spec §8 Q2) and fully streamed
    assert stream.prepared is True
    assert stream.written == b"PDFDATA" * 5000
    assert stream.headers["Content-Type"] == "application/pdf"
    assert "doc.pdf" in stream.headers["Content-Disposition"]


async def test_get_attachment_img_filename_fallback():
    response = _FakeResponse({"Content-Type": "application/octet-stream"})
    request = AsyncMock(return_value=((b"RAW", response), None))
    with patch.object(OdooHelpdesk, "request", request), \
         patch("navigator.actions.odoo_helpdesk.StreamResponse", _FakeStream):
        hd = make_helpdesk()
        stream = await hd.get_attachment_img("/1/2/99", request=object())

    assert "attachment_99" in stream.headers["Content-Disposition"]
    assert stream.written == b"RAW"


# --------------------------------------------------------------------------- #
# 5. find_user() / create_user() no-ops
# --------------------------------------------------------------------------- #
async def test_find_user_and_create_user_are_truthy_noops():
    request = AsyncMock()
    with patch.object(OdooHelpdesk, "request", request):
        hd = make_helpdesk()
        found = await hd.find_user()
        created = await hd.create_user()

    assert found  # truthy -> `if not result: await user.create_user()` never fires
    assert created
    request.assert_not_called()  # no HTTP for either
