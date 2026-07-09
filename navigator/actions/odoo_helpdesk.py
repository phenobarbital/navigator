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

    # -- ticket API (implemented in later FEAT-006 tasks) ----------------------

    async def create(self, **kwargs):
        """Create a new Helpdesk ticket (implemented in TASK-043)."""
        raise NotImplementedError(
            "OdooHelpdesk.create() is implemented in FEAT-006 TASK-043."
        )
