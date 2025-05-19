from typing import Union
import asyncio
from enum import Enum
from datetime import datetime
from aiohttp import web
from navconfig import BASE_DIR
from navconfig.logging import logging
from asyncdb import AsyncDB
from asyncdb.models import Model, Column
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse
from navigator.views import ModelView


# Example Credentials
bigquery_credentials = BASE_DIR.joinpath('env', 'google', 'bigquery.json')
BIGQUERY_CREDENTIALS = {
    "credentials": bigquery_credentials,
    "project_id": "unique-decker-385015"
}

class Zipcode(Model):
    zcta: str = Column(primary_key=True)
    zipcode: str = Column(required=True, label="Zipcode")
    postal_name: str
    state_code: str
    zip_type: str
    latitude: float
    longitude: float
    geoid: str

    def __post_init__(self):
        return super().__post_init__()

    class Meta:
        name: str = 'zipcode_zcta'
        schema = 'troc'
        strict = True


app = Application(enable_jinja2=True)
session = AuthHandler()
session.setup(app)

@app.get('/hello')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(content="<h1>Hello Airport</h1>")


class ZipcodeHandler(ModelView):
    model: Model = Zipcode
    pk: Union[str, list] = ['zcta']
    credentials: dict = BIGQUERY_CREDENTIALS
    driver: str = 'bigquery'

    async def _pre_get(self, *args, **kwargs):
        print(' REQUEST ', self.request)
        app = self.request.app
        session = self.request.get('session')
        print('SESSION ', session)
        print('APP ', app)
        db = app['database']
        async with await db.connection() as conn:
            query = "SELECT * FROM `unique-decker-385015.troc.zipcode_zcta` LIMIT 10"
            result, _ = await conn.query(query)
            print(result)
        template = app['template']
        auth = app['auth']
        return True

    async def _get_data(self, queryparams, args):
        data = await super()._get_data(queryparams, args)
        print('DATA > ', data)
        print('QS ', queryparams)
        return data

    async def _get_callback(self, response: web.Response, result, *args, **kwargs):
        await asyncio.sleep(3)
        print('GET CALLBACK', result)
        return response

    async def _post_callback(self, response: web.Response, result, *args, **kwargs):
        print('POST CALLBACK', result)
        return response

    async def _patch_callback(self, response: web.Response, result, *args, **kwargs):
        print('PATCH CALLBACK', result)
        return response

    async def _put_callback(self, response: web.Response, result, *args, **kwargs):
        print('RESULT > ', result)
        print('RESPONSE > ', response)
        print('PUT CALLBACK')
        return response

    async def on_startup(self, *args, **kwargs):
        print(args, kwargs)
        print('THIS CODE RUN ON STARTUP')

    async def on_shutdown(self, *args, **kwargs):
        print('ESTO OCURRE CUANDO SE DETIENE ==== ')

## two required handlers for a ModelHandler.
ZipcodeHandler.configure(app, '/api/v1/zipcodes')


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        pool = AsyncDB("bigquery", params=BIGQUERY_CREDENTIALS, loop=loop)
        app['database'] = pool
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
