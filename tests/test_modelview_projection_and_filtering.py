"""Unit tests for ``ModelView`` response projection and ``_filter`` handling.

Three defects are covered:

* ``_hidden`` was derived from ``field.metadata["repr"]``, a key datamodel
  never sets, so it was always empty.
* ``_model_response`` used ``_hidden`` as a *whitelist* of columns to return
  instead of an exclusion list, and left ``_fields`` unbound when ``_hidden``
  was ``None``.
* ``_required`` / ``_primaries`` / ``_hidden`` were class attributes of
  ``ModelView`` mutated in place, so the first View instantiated in a process
  filled them for every other subclass.
* ``_filtering`` built its statement with f-strings from the request, and
  never reached the database only because ``get_model.column(field)`` raised
  ``TypeError`` first.
"""
from typing import Optional

import pytest
from datamodel import BaseModel, Column

from navigator.views.model import ModelView


class Alpha(BaseModel):
    """Model whose primary key is ``repr=False`` (the common pattern)."""

    alpha_id: int = Column(required=True, primary_key=True, repr=False)
    name: str = Column(required=True)
    password: str = Column(required=False, secret=True)
    note: str = Column(required=False, repr=False)

    class Meta:
        name = "alpha"
        schema = "public"
        strict = True


class Beta(BaseModel):
    beta_id: int = Column(required=True, primary_key=True)
    label: str = Column(required=False)

    class Meta:
        name = "beta"
        schema = None
        strict = True


class AlphaView(ModelView):
    model = Alpha


class BetaView(ModelView):
    model = Beta


class FakeConn:
    """Captures the statement and the bound arguments of ``query()``."""

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else [{"name": "prefix"}]
        self.error = error
        self.calls: list = []

    async def query(self, sentence, *args, **kwargs):
        self.calls.append((sentence, args))
        return [self.result, self.error]


class FakeHandler:
    """Stands in for ``ConnectionHandler``: awaitable, async context manager."""

    def __init__(self, conn: FakeConn):
        self.conn = conn

    def __call__(self, request=None):
        async def _coro():
            return self

        return _coro()

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Logger:
    def __init__(self):
        self.warnings: list = []

    def warning(self, message):
        self.warnings.append(message)


def make_view(cls, conn: Optional[FakeConn] = None):
    """Build a View without the aiohttp request plumbing ``__init__`` needs."""
    view = object.__new__(cls)
    view.__name__ = cls.model.__name__
    view.model = cls.model
    view._get_model()
    view.get_model = cls.model
    view.logger = _Logger()
    view._request = None  # `request` is a read-only property on aiohttp Views
    view.responses: list = []
    if conn is not None:
        view.handler = FakeHandler(conn)

    def _error(response=None, status=400, **kwargs):
        view.responses.append(("error", status, response))
        return ("error", status, response)

    def _json_response(content=None, status=200, **kwargs):
        view.responses.append(("json", status, content))
        return ("json", status, content)

    view.error = _error
    view.json_response = _json_response
    return view


# ---------------------------------------------------------------------------
# Column metadata
# ---------------------------------------------------------------------------

def test_hidden_derives_from_secret_not_from_repr():
    view = make_view(AlphaView)
    assert view._hidden == ["password"]
    # `repr=False` is NOT a serialization rule: the primary key keeps showing.
    assert "alpha_id" not in view._hidden
    assert "note" not in view._hidden


def test_required_and_primaries_come_from_the_model():
    view = make_view(AlphaView)
    assert view._primaries == ["alpha_id"]
    assert set(view._required) == {"alpha_id", "name"}


def test_metadata_is_per_instance_and_never_touches_the_class():
    alpha = make_view(AlphaView)
    beta = make_view(BetaView)
    assert alpha._primaries == ["alpha_id"]
    assert beta._primaries == ["beta_id"]
    assert alpha._hidden == ["password"]
    assert beta._hidden == []
    # The shared class-level lists stay empty, whatever is instantiated.
    assert ModelView._hidden == []
    assert ModelView._primaries == []
    assert ModelView._required == []


def test_explicit_class_level_hidden_wins():
    class PinnedView(ModelView):
        model = Alpha
        _hidden = ["name"]

    view = make_view(PinnedView)
    assert view._hidden == ["name"]


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def test_hidden_columns_are_excluded_not_returned_alone():
    view = make_view(AlphaView)
    row = Alpha(alpha_id=1, name="jesse", password="s3cret", note="n")
    result = view._project_response(row)
    assert result["alpha_id"] == 1
    assert result["name"] == "jesse"
    assert result["note"] == "n"
    assert "password" not in result


def test_projection_applies_to_every_row_of_a_list():
    view = make_view(AlphaView)
    rows = [
        Alpha(alpha_id=1, name="a", password="x"),
        Alpha(alpha_id=2, name="b", password="y"),
    ]
    result = view._project_response(rows)
    assert [r["name"] for r in result] == ["a", "b"]
    assert all("password" not in r for r in result)


def test_fields_cannot_request_a_hidden_column():
    view = make_view(AlphaView)
    row = Alpha(alpha_id=1, name="jesse", password="s3cret")
    result = view._project_response(row, fields=["password", "name"])
    assert result == {"name": "jesse"}


def test_fields_projection_without_hidden_columns():
    view = make_view(BetaView)
    row = Beta(beta_id=7, label="seven")
    assert view._project_response(row, fields=["label"]) == {"label": "seven"}


def test_dict_rows_are_projected_by_key():
    view = make_view(AlphaView)
    rows = [{"alpha_id": 1, "name": "jesse", "password": "s3cret"}]
    result = view._project_response(rows)
    assert result == [{"alpha_id": 1, "name": "jesse"}]


def test_row_is_passed_through_when_nothing_is_hidden_or_requested():
    view = make_view(BetaView)
    row = Beta(beta_id=1, label="x")
    assert view._project_response(row) is row


# ---------------------------------------------------------------------------
# _filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filtering_is_skipped_without_the_parameter():
    view = make_view(AlphaView, FakeConn())
    assert await view._filtering({}) is None


@pytest.mark.asyncio
async def test_filtering_rejects_a_malformed_parameter():
    conn = FakeConn()
    view = make_view(AlphaView, conn)
    kind, status, _ = await view._filtering({"_filter": "name"})
    assert (kind, status) == ("error", 400)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_filtering_rejects_an_unknown_column():
    conn = FakeConn()
    view = make_view(AlphaView, conn)
    kind, status, _ = await view._filtering({"_filter": "nope=x"})
    assert (kind, status) == ("error", 400)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_filtering_rejects_a_hidden_column():
    conn = FakeConn()
    view = make_view(AlphaView, conn)
    kind, status, _ = await view._filtering({"_filter": "password=s"})
    assert (kind, status) == ("error", 400)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_filtering_binds_the_value_as_a_parameter():
    conn = FakeConn()
    view = make_view(AlphaView, conn)
    kind, status, content = await view._filtering({"_filter": "name=jes"})
    assert (kind, status) == ("json", 200)
    assert content == conn.result
    sentence, args = conn.calls[0]
    assert '"name"::text LIKE $1' in sentence
    assert '"public"."alpha"' in sentence
    assert args == ("jes%",)


@pytest.mark.asyncio
async def test_filtering_never_interpolates_a_hostile_value():
    conn = FakeConn()
    view = make_view(AlphaView, conn)
    hostile = "' OR 1=1; DROP TABLE public.alpha; --"
    await view._filtering({"_filter": f"name={hostile}"})
    sentence, args = conn.calls[0]
    assert "DROP TABLE" not in sentence
    assert "OR 1=1" not in sentence
    assert args == (f"{hostile}%",)


@pytest.mark.asyncio
async def test_filtering_quotes_a_schemaless_table():
    conn = FakeConn()
    view = make_view(BetaView, conn)
    await view._filtering({"_filter": "label=x"})
    sentence, _ = conn.calls[0]
    assert 'FROM "beta"' in sentence


@pytest.mark.asyncio
async def test_filtering_returns_none_on_a_driver_error():
    conn = FakeConn(result=None, error="boom")
    view = make_view(AlphaView, conn)
    assert await view._filtering({"_filter": "name=jes"}) is None
    assert view.logger.warnings
