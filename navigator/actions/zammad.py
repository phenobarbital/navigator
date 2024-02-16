from navigator.exceptions import ConfigError
from navigator.conf import (
    ZAMMAD_INSTANCE,
    ZAMMAD_TOKEN,
    ZAMMAD_DEFAULT_CUSTOMER,
    ZAMMAD_DEFAULT_GROUP,
    ZAMMAD_DEFAULT_CATALOG,
    ZAMMAD_ORGANIZATION,
    ZAMMAD_DEFAULT_ROLE
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
        self.credentials = {}
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
        service_catalog = self._kwargs.pop(
            'service_catalog',
            ZAMMAD_DEFAULT_CATALOG
        )
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
            "service_catalog": service_catalog,
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
            "service_catalog": service_catalog,
            "article": article
        }
        try:
            result, error = await self.request(
                self.url, self.method, data=data
            )
            if error is not None:
                msg = error['message']
                raise ConfigError(
                    f"Error creating Zammad Ticket: {msg}"
                )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error creating Zammad Ticket: {e}"
            ) from e

    async def create_user(self):
        """create_user.

        Create a new User.

        TODO: Adding validation with dataclasses.
        """
        self.url = f"{ZAMMAD_INSTANCE}api/v1/users"
        self.method = 'post'
        organization = self._kwargs.pop(
            'organization',
            ZAMMAD_ORGANIZATION
        )
        roles = self._kwargs.pop('roles', [ZAMMAD_DEFAULT_ROLE])
        if not isinstance(roles, list):
            roles = [
                "Customer"
            ]
        data = {
            "organization": organization,
            "roles": roles,
            **self._kwargs
        }
        try:
            result, error = await self.request(
                self.url, self.method, data=data
            )
            if error is not None:
                msg = error['message']
                raise ConfigError(
                    f"Error creating User: {msg}"
                )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error creating Zammad User: {e}"
            ) from e

    async def find_user(self, search: dict = None):
        """find_user.

        Find existing User on Zammad.

        TODO: Adding validation with dataclasses.
        """
        self.url = f"{ZAMMAD_INSTANCE}api/v1/users/search"
        self.method = 'get'
        search = self._kwargs.pop('search', search)
        if not isinstance(search, dict):
            raise ConfigError(
                f"Search Dictionary is required, current: {search}"
            )
        # Joining all key:value pairs with a delimiter
        query_string = ','.join(
            f"{key}:{value}" for key, value in search.items()
        )
        query_string = f"query={query_string}"
        self.url = self.build_url(
            self.url,
            queryparams=query_string
        )
        try:
            result, _ = await self.request(
                self.url, self.method
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error Searching Zammad User: {e}"
            ) from e

    async def get_ticket(self, ticket_id: dict = None):
        """get_ticket.

        Get a Ticket on Zammad.

        TODO: Adding validation with dataclasses.
        """
        self.url = f"{ZAMMAD_INSTANCE}/api/v1/tickets/{ticket_id}"
        self.method = 'get'
        try:
            result, _ = await self.request(
                self.url, self.method
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error Getting Zammad Ticket: {e}"
            ) from e
