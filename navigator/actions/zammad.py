from navigator.exceptions import ConfigError
from navigator.conf import (
    ZAMMAD_INSTANCE,
    ZAMMAD_TOKEN,
    ZAMMAD_DEFAULT_CUSTOMER,
    ZAMMAD_DEFAULT_GROUP,
    ZAMMAD_DEFAULT_CATALOG
)
from .ticket import AbstractTicket
from .rest import RESTAction

class Zammad(AbstractTicket, RESTAction):
    """Zammad.

    Managing Tickets using Zammad.

    TODO: Logic for refreshing token.
    """
    auth_type = 'apikey'
    token_type = 'Bearer'
    article_base = {
        "type": "note",
        "internal": False
    }
    permissions_base = {
        "name": "api_user_token",
        "label": "User Token",
        "permissions": ["api"]
    }
    data_format: str = 'raw'

    def __init__(self, *args, **kwargs):
        super(Zammad, self).__init__(*args, **kwargs)
        self.auth = {
            "apikey": ZAMMAD_TOKEN
        }

    async def get_user_token(self):
        """get_user_token.


        Usage: using X-On-Behalf-Of to getting User Token.

        """
        self.url = f"{ZAMMAD_INSTANCE}api/v1/user_access_token"
        self.method = 'post'
        permissions: list = self._kwargs.pop('permissions', [])
        user = self._kwargs.pop('user', ZAMMAD_DEFAULT_CUSTOMER)
        token_name = self._kwargs.pop('token_name')
        self.headers['X-On-Behalf-Of'] = user
        self.accept = 'application/json'
        ## create payload for access token:
        data = {**self.permissions_base, **{
            "name": token_name,
            permissions: permissions
        }}
        result, _ = await self.async_request(
            self.url, self.method, data, use_json=True
        )
        return result['token']

    async def list_tickets(self):
        """list_tickets.

            Getting a List of all opened tickets by User.
        """
        self.method = 'get'
        self.url = f"{ZAMMAD_INSTANCE}api/v1/tickets/search?query=state_id:%201%20OR%20state_id:%202%20OR%20state_id:%203"
        try:
            result, _ = await self.request(
                self.url, self.method
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error getting Zammad Tickets: {e}"
            ) from e

    async def update(self, ticket: int):
        """list_tickets.

            Getting a List of all opened tickets by User.
        """
        self.method = 'post'
        title = self._kwargs.pop('title', None)
        customer = self._kwargs.pop('customer', ZAMMAD_DEFAULT_CUSTOMER)
        group = self._kwargs.pop('group', ZAMMAD_DEFAULT_GROUP)
        self.ticket = self._kwargs.pop('ticket', ticket)
        ticket_type = self._kwargs.pop('type', 'note')
        service_catalog = self._kwargs.pop('service_catalog', ZAMMAD_DEFAULT_CATALOG)
        user = self._kwargs.pop('user', None)
        if user:
            self.headers['X-On-Behalf-Of'] = user
        if not self.ticket:
            raise ConfigError(
                "Ticket ID is required."
            )
        self.url = f"{ZAMMAD_INSTANCE}api/v1/tickets/{self.ticket}"
        article = {
            "subject": self._kwargs.pop('subject', title),
            "body": self._kwargs.pop('body', None),
            "type": ticket_type,
            "internal": True
        }
        data = {
            "title": title,
            "group": group,
            "customer": customer,
            "catalog": service_catalog,
            "article": article
        }
        try:
            result, _ = await self.request(
                self.url, self.method, data=data
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error Updating Zammad Ticket: {e}"
            ) from e

    async def create(self):
        """create.

        Create a new Ticket.
        """
        self.url = f"{ZAMMAD_INSTANCE}api/v1/tickets"
        self.method = 'post'
        group = self._kwargs.pop('group', ZAMMAD_DEFAULT_GROUP)
        title = self._kwargs.pop('title', None)
        service_catalog = self._kwargs.pop('service_catalog')
        customer = self._kwargs.pop('customer', ZAMMAD_DEFAULT_CUSTOMER)
        user = self._kwargs.pop('user', None)
        if user:
            self.headers['X-On-Behalf-Of'] = user
        article = {
            "subject": self._kwargs.pop('subject', title),
            "body": self._kwargs.pop('body', None)
        }
        article = {**self.article_base, **article}
        data = {
            "title": title,
            "group": group,
            "customer": customer,
            "catalog": service_catalog,
            "article": article
        }
        try:
            result, _ = await self.request(
                self.url, self.method, data=data
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error creating Zammad Ticket: {e}"
            ) from e
