import base64
import magic
from urllib.parse import quote_plus
from ..exceptions import ConfigError
from ..conf import (
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
        self.timeout = 360
        self.credentials = {}
        self.zammad_instance = self._kwargs.pop('zammad_instance', ZAMMAD_INSTANCE)
        self.zammad_token = self._kwargs.pop('zammad_token', ZAMMAD_TOKEN)
        self.auth = {
            "apikey": self.zammad_token
        }

    async def get_user_token(self):
        """get_user_token.


        Usage: using X-On-Behalf-Of to getting User Token.

        """
        self.url = f"{self.zammad_instance}api/v1/user_access_token"
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

    async def list_tickets(self, **kwargs):
        """list_tickets.

            Getting a List of all opened tickets by User.
        """
        self.method = 'get'
        states = kwargs.pop('state_id', [1, 2, 3])  # Open by Default
        per_page = kwargs.pop('per_page', 100) # Max tickets count per page
        page = 1  # First Page
        all_tickets = []  # List for tickets
        all_assets = {}  # Dict for all assets
        tickets_count = 0  # Total tickets count

        if ',' in states:
            states = states.split(',')

        if states:
            # Then, after getting the states, we can join them with a delimiter
            # state_id: 1 OR state_id: 2 OR state_id: 3
            state_id_parts = ["state_id:{}".format(state) for state in states[1:]]
            query_string = "state_id:{} OR ".format(states[0]) + " OR ".join(state_id_parts)
            qs = quote_plus(query_string)
        else:
            qs = "state_id:%201%20OR%20state_id:%202%20OR%20state_id:%203"

        # Pagination Loop
        while True:
            self.url = f"{self.zammad_instance}api/v1/tickets/search?query={qs}&page={page}&limit={per_page}"

            try:
                result, _ = await self.request(self.url, self.method)

                # Get actual tickets and add to array
                tickets = result.get("tickets", [])
                if not tickets or len(tickets) == 0:
                    break  # If there are no more tickets on the current page, exit the loop
                all_tickets.extend(tickets)

                # Get actual assets and add to dict
                assets = result.get("assets", {})
                for key, value in assets.items():
                    if key not in all_assets:
                        all_assets[key] = value
                    else:
                        # If is a list
                        if isinstance(value, list):
                            all_assets[key].extend(value)
                        # If is a dict
                        elif isinstance(value, dict):
                            all_assets[key].update(value)
                        else:
                            all_assets[key] = value

                page += 1  # Next page

            except Exception as e:
                raise ConfigError(
                    f"Error getting Zammad Tickets: {e}"
                ) from e
        tickets_count = len(all_tickets)

        return {
            "tickets": all_tickets,
            "tickets_count": tickets_count,
            "assets": all_assets
        }

    async def update(self, ticket: int, **kwargs):
        """update.

           Update an Existing Ticket.
        """
        self.method = 'put'
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
        self.url = f"{self.zammad_instance}api/v1/tickets/{self.ticket}"
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
            "article": article,
            **kwargs
        }
        data = self._encoder.dumps(data)
        try:
            result, _ = await self.request(
                self.url, self.method, data=data
            )
            return result
        except Exception as e:
            raise ConfigError(
                f"Error Updating Zammad Ticket: {e}"
            ) from e

    async def create(self, **kwargs):
        """create.

        Create a new Ticket.
        """
        supported_types = [
            'text/plain', 'image/png', 'image/jpeg', 'image/gif', 'application/pdf',
            'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv'
        ]
        self.url = f"{self.zammad_instance}api/v1/tickets"
        self.method = 'post'
        group = self._kwargs.pop('group', ZAMMAD_DEFAULT_GROUP)
        title = self._kwargs.pop('title', None)
        service_catalog = self._kwargs.pop('service_catalog', None)
        customer = self._kwargs.pop('customer', ZAMMAD_DEFAULT_CUSTOMER)
        _type = self._kwargs.pop('type', 'Incident')
        user = self._kwargs.pop('user', None)
        attachments = []
        for attachment in self._kwargs.get('attachments', []):
            mime_type = attachment.get('mime_type')
            encoded_data = attachment.get('data')
            if not mime_type:
                try:
                    # Decode the Base64-encoded data to get the binary content
                    binary_data = base64.b64decode(encoded_data)
                    # Use python-magic to determine the file's MIME type
                    mime_type = magic.from_buffer(binary_data, mime=True)
                except Exception:
                    mime_type = 'text/plain'
            attach = {
                "mime-type": mime_type,
                "filename": attachment['filename'],
                "data": encoded_data
            }
            if mime_type in supported_types:
                attachments.append(attach)
        if user:
            self.headers['X-On-Behalf-Of'] = user
        article = {
            "subject": self._kwargs.pop('subject', title),
            "body": self._kwargs.pop('body', None),
            "type": self._kwargs.pop('article_type', 'note'),
        }
        article = {**self.article_base, **article}
        if attachments:
            article['attachments'] = attachments
        data = {
            "title": title,
            "group": group,
            "customer": customer,
            "type": _type,
            "service_catalog": service_catalog,
            "article": article,
            **kwargs
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
        self.url = f"{self.zammad_instance}api/v1/users"
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
        self.url = f"{self.zammad_instance}api/v1/users/search"
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
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Error Searching Zammad User: {e}"
            ) from e

    async def get_ticket(self, ticket_id: dict = None):
        """get_ticket.

        Get a Ticket on Zammad.

        TODO: Adding validation with dataclasses.
        """
        self.url = f"{self.zammad_instance}/api/v1/tickets/{ticket_id}"
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
    
    async def get_articles(self, ticket_id: int):
        """get_articles

        get all articles of a ticket

        Args:
            ticket_id (int): id of ticket
        """
        self.url = f"{self.zammad_instance}/api/v1/ticket_articles/by_ticket/{ticket_id}"
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
