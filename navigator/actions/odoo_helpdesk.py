"""OdooHelpdesk action.

Drop-in replacement for the :class:`~navigator.actions.zammad.Zammad` action that
talks to the Odoo 19 Helpdesk webhook (``troc_helpdesk`` module) instead of Zammad.

It exposes the exact same public method surface as ``Zammad``
(``create``, ``update``, ``get_ticket``, ``list_tickets``, ``get_articles``,
``get_attachment_img``, ``find_user``, ``create_user``) and returns
Zammad-shaped dictionaries, so migrating a tenant is just swapping the import
and the credentials block -- no changes to view logic or response parsing.

See ``sdd/specs/odoo-helpdesk-action.spec.md`` (FEAT-006, NAV-9101 / G10).

.. note::
    This class must **not** set ``auth_type = 'apikey'``: that would make
    :class:`~navigator.actions.rest.RESTAction` inject an
    ``Authorization: Bearer <token>`` header, which the Odoo webhook rejects.
    The API key is sent via the ``X-Helpdesk-Api-Key`` header, set directly in
    :meth:`__init__` (mirroring the direct-header idiom of the existing
    ``navigator.actions.odoo.Odoo`` class).
"""
from urllib.parse import urlencode

from ..exceptions import ConfigError
from ..conf import (
    ODOO_HELPDESK_INSTANCE,
    ODOO_HELPDESK_API_KEY,
    ODOO_HELPDESK_COMPANY,
)
from .ticket import AbstractTicket
from .rest import RESTAction


class OdooHelpdesk(AbstractTicket, RESTAction):
    """OdooHelpdesk.

    Manage Helpdesk tickets through the Odoo webhook while presenting the same
    interface and Zammad-shaped responses as the ``Zammad`` action.
    """

    def __init__(self, *args, **kwargs):
        super(OdooHelpdesk, self).__init__(*args, **kwargs)
        self.timeout = 360
        self.credentials = {}
        # instance/api_key/company follow the Zammad ``pop-with-conf-fallback``
        # idiom so callers can override per request.
        self.instance = self._kwargs.pop('instance', ODOO_HELPDESK_INSTANCE)
        self.api_key = self._kwargs.pop('api_key', ODOO_HELPDESK_API_KEY)
        self.company_id = self._kwargs.pop('company_id', ODOO_HELPDESK_COMPANY)
        # Optional agent impersonation (Odoo ``as_user`` query parameter).
        self.as_user = self._kwargs.pop('as_user', None)
        # Direct header -- do NOT set ``auth_type = 'apikey'`` (see module docstring).
        self.headers['X-Helpdesk-Api-Key'] = self.api_key

    # -- helpers ---------------------------------------------------------------

    def _company_qs(self, extra: dict = None) -> str:
        """Build the query string for a Helpdesk GET call.

        ``company_id`` is mandatory on every Odoo Helpdesk GET (a missing value
        yields a 400 server-side), so this raises early instead of issuing a
        request that is guaranteed to fail.

        Args:
            extra: Additional query parameters. ``None`` values are dropped.

        Returns:
            An URL-encoded query string (without the leading ``?``).

        Raises:
            ConfigError: If ``company_id`` is not configured.
        """
        if self.company_id in (None, ''):
            raise ConfigError(
                "company_id is required for Odoo Helpdesk GET calls."
            )
        params = {'company_id': self.company_id}
        if self.as_user:
            params['as_user'] = self.as_user
        if extra:
            params.update({k: v for k, v in extra.items() if v is not None})
        return urlencode(params)

    def _to_zammad_ticket(self, odoo: dict) -> dict:
        """Adapt a serialized Odoo Helpdesk ticket into a Zammad-shaped dict.

        The returned dict includes the keys tenant views read today -- notably
        ``number`` (callers do ``new_ticket.get("number")``), which is mapped to
        the Odoo sequence ``name`` (e.g. ``"TICKET/0042"``; see spec §8 Q1). The
        raw Odoo record is preserved under the ``odoo`` key for forward-compat.

        Args:
            odoo: A single serialized Odoo ticket record.

        Returns:
            A flat, Zammad-shaped ticket dict.
        """
        def _name(value):
            return (value or {}).get('name') if isinstance(value, dict) else value

        return {
            'id': odoo.get('id'),
            'number': odoo.get('name'),
            'title': odoo.get('subject'),
            'subject': odoo.get('subject'),
            'body': odoo.get('description'),
            'state': _name(odoo.get('stage')),
            'priority': _name(odoo.get('priority')),
            'group': _name(odoo.get('team')),
            'customer': _name(odoo.get('partner')),
            'owner': _name(odoo.get('owner')),
            'category': _name(odoo.get('category')),
            'attachments': odoo.get('attachments', []),
            'extra_fields': odoo.get('extra_fields', []),
            'odoo': odoo,
        }

    def _parse_attachment_path(self, path: str) -> str:
        """Extract the trailing attachment id from a Zammad-style path.

        Zammad's ``get_attachment_img`` receives a path shaped like
        ``"/{ticket}/{article}/{attachment}"``; the Odoo webhook only needs the
        trailing attachment id.

        Args:
            path: The Zammad-style attachment path (e.g. ``"/12/34/56"``).

        Returns:
            The trailing id as a string (e.g. ``"56"``).
        """
        return str(path).strip('/').split('/')[-1]

    # Adapter-level control keys that must never be forwarded as ticket fields
    # (credentials / routing internals / dispatch), stripped before POST/PUT.
    _control_keys = ('instance', 'api_key', 'company_id', 'as_user', 'action')

    def _ticket_payload(self, kwargs: dict) -> dict:
        """Build the flat webhook body from caller kwargs.

        The Odoo webhook maps standard keys to native fields and routes
        tenant-prefixed / unrecognized keys to "extra fields" server-side, so
        the faithful drop-in behaviour is to forward the payload flat after
        removing adapter-level control keys.

        Args:
            kwargs: The keyword arguments the caller passed to ``create``/``update``.

        Returns:
            The flat JSON-serializable body to send to the webhook.
        """
        payload = dict(kwargs)
        for key in self._control_keys:
            payload.pop(key, None)
        return payload

    # -- ticket API ------------------------------------------------------------

    async def get_ticket(self, ticket_id, user: str = None):
        """Fetch a single Helpdesk ticket, adapted to the Zammad shape.

        Args:
            ticket_id: The Odoo ticket id.
            user: Optional agent login to impersonate (``as_user``); overrides
                the instance-level ``as_user`` for this call.

        Returns:
            A Zammad-shaped ticket dict with top-level ``subject``/``body``.

        Raises:
            ConfigError: On a webhook error or a missing ``company_id``.
        """
        qs = self._company_qs({'as_user': user} if user else None)
        self.url = f"{self.instance}helpdesk/ticket/{ticket_id}?{qs}"
        self.method = 'get'
        try:
            result, error = await self.request(self.url, self.method)
            if error is not None:
                raise ConfigError(
                    f"Error Getting Odoo Helpdesk Ticket: {error['message']}"
                )
            return self._to_zammad_ticket(result['ticket'])
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Error Getting Odoo Helpdesk Ticket: {e}"
            ) from e

    async def create(self, **kwargs):
        """Create a new Helpdesk ticket.

        The webhook ``POST`` returns a flat ``{ok, ticket_id, ticket_name}``
        with no full record, so this performs a follow-up ``GET`` on the new id
        to build the Zammad-shaped dict (which includes the ``number`` key
        downstream callers rely on).

        Returns:
            A Zammad-shaped ticket dict (with a ``number`` key).

        Raises:
            ConfigError: On a webhook error.
        """
        self.url = f"{self.instance}helpdesk/ticket"
        self.method = 'post'
        data = self._ticket_payload(kwargs)
        try:
            result, error = await self.request(
                self.url, self.method, data=data
            )
            if error is not None:
                raise ConfigError(
                    f"Error creating Odoo Helpdesk Ticket: {error['message']}"
                )
            ticket_id = result['ticket_id']
            return await self.get_ticket(ticket_id)
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Error creating Odoo Helpdesk Ticket: {e}"
            ) from e

    async def update(self, ticket: int, **kwargs):
        """Update an existing Helpdesk ticket.

        The webhook ``PUT`` returns the fully serialized record. Note that a
        ``body`` in the payload is posted as an internal chatter note
        server-side (not a description change), so this does not attempt to
        read a description change back out of the response.

        Args:
            ticket: The Odoo ticket id to update.
            **kwargs: Fields to update (same flat semantics as ``create``).

        Returns:
            A Zammad-shaped ticket dict built from the updated record.

        Raises:
            ConfigError: On a webhook error.
        """
        self.url = f"{self.instance}helpdesk/ticket/{ticket}"
        self.method = 'put'
        payload = self._ticket_payload(kwargs)
        payload.pop('ticket', None)  # id travels in the URL, not the body
        # PUT does not serialize internally in RESTAction.request() -> pre-dump
        # (mirrors Zammad.update).
        data = self._encoder.dumps(payload)
        try:
            result, error = await self.request(
                self.url, self.method, data=data
            )
            if error is not None:
                raise ConfigError(
                    f"Error Updating Odoo Helpdesk Ticket: {error['message']}"
                )
            return self._to_zammad_ticket(result['ticket'])
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Error Updating Odoo Helpdesk Ticket: {e}"
            ) from e

    async def list_tickets(self, user: str = None, **kwargs):
        """List Helpdesk tickets, adapted to the Zammad list shape.

        Args:
            user: Optional agent login to impersonate (``as_user``).
            **kwargs: Optional Odoo filters (``team_id``, ``stage_id``,
                ``limit``, ``offset``). A Zammad-only ``state_id`` kwarg is
                dropped, not forwarded.

        Returns:
            ``{"tickets": [...], "tickets_count": N,
               "assets": {"Ticket": {"<id>": <zammad-shaped>, ...}}}``.

        Raises:
            ConfigError: On a webhook error or a missing ``company_id``.
        """
        kwargs.pop('state_id', None)  # Zammad-only; Odoo has no such filter
        extra = {'as_user': user} if user else {}
        for key in ('team_id', 'stage_id', 'limit', 'offset'):
            if kwargs.get(key) is not None:
                extra[key] = kwargs[key]
        qs = self._company_qs(extra)
        self.url = f"{self.instance}helpdesk/tickets?{qs}"
        self.method = 'get'
        try:
            result, error = await self.request(self.url, self.method)
            if error is not None:
                raise ConfigError(
                    f"Error listing Odoo Helpdesk Tickets: {error['message']}"
                )
            tickets = result.get('tickets', [])
            return {
                "tickets": tickets,
                "tickets_count": result.get('count', len(tickets)),
                "assets": {
                    "Ticket": {
                        str(t['id']): self._to_zammad_ticket(t)
                        for t in tickets
                    }
                },
            }
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Error listing Odoo Helpdesk Tickets: {e}"
            ) from e
