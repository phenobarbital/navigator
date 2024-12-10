from navconfig import config
from .rest import RESTAction

ODOO_HOST = config.get('ODOO_HOST')
ODOO_APIKEY = config.get('ODOO_APIKEY')


class Odoo(RESTAction):

    def __init__(self, *args, **kwargs):
        super(Odoo, self).__init__(*args, **kwargs)
        self.instance = self._kwargs.pop('instance', ODOO_HOST)
        self.api_key = self._kwargs.pop('api_key', ODOO_APIKEY)
        self.credentials = {}
        self.auth = {}
        self.method = 'post'
        self.accept = 'application/json'
        self.headers['Content-Type'] = 'application/json'
        self.headers['api-key'] = self.api_key


    async def run(self):
        pass

    async def fieldservice_order(self, data):
        url = f'{self.instance}api/webhook/fieldservice_order'
        result, error = await self.async_request(
            url, self.method, data, use_json=True
        )
        
        return result or error['message']

    
    async def create_lead(self, data):
        url = f'{self.instance}api/webhook/lead'
        result, error = await self.async_request(
            url, self.method, data, use_json=True
        )
        
        return result or error['message']