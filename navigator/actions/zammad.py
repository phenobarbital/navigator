from navigator.exceptions import ConfigError
from navigator.conf import (
    ZAMMAD_INSTANCE,
    ZAMMAD_TOKEN,
    ZAMMAD_DEFAULT_CUSTOMER,
    ZAMMAD_DEFAULT_GROUP
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
    data_format: str = 'raw'

    def __init__(self, *args, **kwargs):
        super(Zammad, self).__init__(*args, **kwargs)
        self.auth = {
            "apikey": ZAMMAD_TOKEN
        }

    async def close(self):
        pass

    async def open(self):
        pass

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
