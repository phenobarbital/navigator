import json
from navigator.exceptions import ConfigError
from navconfig import config
from .ticket import AbstractTicket
from .rest import RESTAction

AVOCHATO_INSTANCE = 'https://www.avochato.com/v1'
AVOCHATO_ID = config.get('AVOCHATO_ID')
AVOCHATO_SECRET = config.get('AVOCHATO_SECRET')


class Avochato(AbstractTicket, RESTAction):
    '''
        TODO: Manage ConnectionError exception to return status code and error message in an easier way
    '''

    def __init__(self, *args, **kwargs):
        super(Avochato, self).__init__(*args, **kwargs)
        self.credentials = {}
        self.auth = {}


    async def run(self):
        pass

    async def create(self):
        pass


    async def get_broadcasts(self):
        self.url = f'{AVOCHATO_INSTANCE}/broadcasts?auth_id={AVOCHATO_ID}&auth_secret={AVOCHATO_SECRET}'
        self.method = 'get'
        self.accept = 'application/json'
        try:
            result, _ = await self.async_request(
                self.url, self.method, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)


    async def set_broadcast(self, name, message, via_phone_numbers, media_url=None):
        args = {}
        self.url = f'{AVOCHATO_INSTANCE}/broadcasts'
        self.method = 'post'
        self.accept = 'application/json'
        if media_url:
            args['media_url'] = media_url

        data = {
            "auth_id": AVOCHATO_ID,
            "auth_secret": AVOCHATO_SECRET,
            "name": name,
            "message": message,
            "via_phone_numbers": via_phone_numbers,
            **args
        }
        try:
            result, error = await self.async_request(
                self.url, self.method, data, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)


    async def update_broadcast(self, broadcast_id, name=None, message=None, via_phone_numbers=None, media_url=None):
        args = {}
        self.url = f'{AVOCHATO_INSTANCE}/broadcasts/{broadcast_id}'
        self.method = 'post'
        self.accept = 'application/json'
        if name:
            args['name'] = name
        if message:
            args['message'] = message
        if via_phone_numbers:
            args['via_phone_numbers'] = via_phone_numbers
        if media_url:
            args['media_url'] = media_url

        data = {
            "auth_id": AVOCHATO_ID,
            "auth_secret": AVOCHATO_SECRET,
            **args
        }
        try:
            result, error = await self.async_request(
                self.url, self.method, data, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)

    
    async def publish_broadcast(self, broadcast_id):
        self.url = f'{AVOCHATO_INSTANCE}/broadcasts/{broadcast_id}/publish'
        self.method = 'post'
        self.accept = 'application/json'
        data = {
            "auth_id": AVOCHATO_ID,
            "auth_secret": AVOCHATO_SECRET,
            "asap": True
        }
        try:
            result, error = await self.async_request(
                self.url, self.method, data, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)


    async def get_messages(self):
        self.url = f'{AVOCHATO_INSTANCE}/messages?auth_id={AVOCHATO_ID}&auth_secret={AVOCHATO_SECRET}'
        self.method = 'get'
        self.accept = 'application/json'
        try:
            result, _ = await self.async_request(
                self.url, self.method, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)


    async def send_message(self, phone, message, from_phone, media_url=None, send_as_user_id=None):
        args = {}
        self.url = f'{AVOCHATO_INSTANCE}/messages'
        self.method = 'post'
        self.accept = 'application/json'
        if media_url:
            args['media_url'] = media_url
        if send_as_user_id:
            args['send_as_user_id'] = send_as_user_id
        data = {
            "auth_id": AVOCHATO_ID,
            "auth_secret": AVOCHATO_SECRET,
            "phone": phone,
            "message": message,
            "from": from_phone,
            **args
        }
        try:
            result, error = await self.async_request(
                self.url, self.method, data, use_json=True
            )
            return result
        except ConnectionError as err:
            error = str(err).split(': ', 1)[1].replace("'", '"')
            return json.loads(error)
