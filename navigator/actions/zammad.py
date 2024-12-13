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
from aiohttp.web import Response
from io import BytesIO


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
        """Retrieve a user token using X-On-Behalf-Of for API interactions."""
        self.url = f"{self.zammad_instance}api/v1/user_access_token"
        self.method = 'post'
        permissions: list = self._kwargs.pop('permissions', [])
        user = self._kwargs.pop('user', ZAMMAD_DEFAULT_CUSTOMER)
        token_name = self._kwargs.pop('token_name')
        self.headers['X-On-Behalf-Of'] = user
        self.accept = 'application/json'
        # Create payload for access token
        data = {**self.permissions_base, **{
            "name": token_name,
            permissions: permissions
        }}
        result, _ = await self.async_request(
            self.url, self.method, data, use_json=True
        )
        return result['token']

    async def list_tickets(self, **kwargs):
        """Retrieve a list of all opened tickets by the user."""
        self.method = 'get'
        states = kwargs.pop('state_id', [1, 2, 3])  # Open by default
        per_page = kwargs.pop('per_page', 100)  # Max tickets count per page
        page = 1  # Start with the first page
        all_tickets = []  # List for tickets
        all_assets = {}  # Dictionary for all assets
        tickets_count = 0  # Total tickets count

        if ',' in states:
            states = states.split(',')

        if states:
            # Combine states into a query string
            state_id_parts = ["state_id:{}".format(state) for state in states[1:]]
            query_string = "state_id:{} OR ".format(states[0]) + " OR ".join(state_id_parts)
            qs = quote_plus(query_string)
        else:
            qs = "state_id:%201%20OR%20state_id:%202%20OR%20state_id:%203"

        # Pagination loop
        while True:
            self.url = f"{self.zammad_instance}api/v1/tickets/search?query={qs}&page={page}&limit={per_page}"

            try:
                result, _ = await self.request(self.url, self.method)

                # Add tickets to the list
                tickets = result.get("tickets", [])
                if not tickets or len(tickets) == 0:
                    break  # Exit if no more tickets on the current page
                all_tickets.extend(tickets)

                # Add assets to the dictionary
                assets = result.get("assets", {})
                for key, value in assets.items():
                    if key not in all_assets:
                        all_assets[key] = value
                    else:
                        if isinstance(value, list):
                            all_assets[key].extend(value)
                        elif isinstance(value, dict):
                            all_assets[key].update(value)
                        else:
                            all_assets[key] = value

                page += 1  # Move to the next page

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

    async def get_attachment_img(self, attachment: str):
        """Retrieve an attachment from a ticket.

        Args:
            attachment (str): The attachment path from the ticket.

        Returns:
            Response: HTTP Response containing the attachment file.

        Raises:
            ConfigError: If an error occurs during the request or processing.
        """
        self.url = f"{self.zammad_instance}/api/v1/ticket_attachment{attachment}"
        self.method = 'get'
        self.file_buffer = True

        try:
            # Perform the request to retrieve the attachment
            result, error = await self.request(self.url, self.method)

            # Handle errors in the response
            if error:
                raise ConfigError(f"Error Getting Zammad Attachment: {error.get('message', 'Unknown error')}")

            # Separate the binary image data and the response headers
            image, response = result

            # Validate and retrieve headers
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            if not content_type.startswith('image/'):
                raise ConfigError("The attachment is not a valid image file.")

            content_disposition = response.headers.get('Content-Disposition')
            if not content_disposition or 'filename=' not in content_disposition:
                raise ConfigError("Attachment filename missing in response headers.")

            # Extract the filename from Content-Disposition
            image_name = content_disposition.split('filename=')[-1].strip('"')

            # Convert BytesIO to binary data if necessary
            if isinstance(image, BytesIO):
                image_data = image.getvalue()
            else:
                image_data = image  # Use as-is if already binary data

            # Construct and return the HTTP response
            return Response(
                body=image_data,
                headers={
                    'Content-Type': content_type,
                    'Content-Disposition': f'attachment; filename="{image_name}"',
                    'Content-Length': str(len(image_data)),
                    'Content-Transfer-Encoding': 'binary',
                }
            )
        except KeyError as e:
            raise ConfigError(f"Missing required header: {e}") from e
        except Exception as e:
            raise ConfigError(f"Unexpected error while fetching attachment: {e}") from e
