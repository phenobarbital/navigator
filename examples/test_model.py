from typing import Union
import asyncio
from enum import Enum
from datetime import datetime
from aiohttp import web
from navconfig.logging import logging
from asyncdb import AsyncPool
from asyncdb.models import Model, Column
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse
from navigator.views import ModelView
from navigator.conf import PG_USER, PG_PWD, PG_HOST, PG_PORT

# Example DSN:
dsn = f'postgresql://{PG_USER}:{PG_PWD}@{PG_HOST}:{PG_PORT}/pruebas'

class AirportType(Enum):
    """
    Enum for Airport Types.
    """
    CITY = 1
    INTERNATIONAL = 2
    DOMESTIC = 3


class Country(Model):
    country_code: str = Column(primary_key=True)
    country: str

class Airport(Model):
    iata: str = Column(primary_key=True, required=True, label='IATA Code', default='AEP')
    airport: str = Column(required=True, label="Airport Name")
    airport_type: AirportType = Column(
        required=True,
        label='Airport Type',
        choices=AirportType,
        default=AirportType.CITY
    )
    city: str
    country: str  # = Column(foreign_key=Country.country)
    created_by: int
    created_at: datetime = Column(default=datetime.now(), repr=False)

    def __post_init__(self):
        return super().__post_init__()

    def geography(self):
        return self.city, self.country

    class Meta:
        name: str = 'airports'
        schema = 'public'
        strict = True


app = Application(enable_jinja2=True)
session = AuthHandler()
session.setup(app)

@app.get('/hello')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(content="<h1>Hello Airport</h1>")


class AirportHandler(ModelView):
    model: Model = Airport
    pk: Union[str, list] = ['iata']
    dsn: str = dsn

    async def _pre_get(self, *args, **kwargs):
        print(' REQUEST ', self.request)
        app = self.request.app
        session = self.request.get('session')
        print('SESSION ', session)
        print('APP ', app)
        db = app['database']
        async with await db.acquire() as conn:
            query = "SELECT * FROM public.airports"
            result, _ = await conn.query(query)
            print(result)
        template = app['template']
        auth = app['auth']
        return True

    async def _get_data(self, queryparams, args):
        data = await super()._get_data(queryparams, args)
        async with await self.handler(request=self.request) as conn:
            # Country.Meta.connection = conn
            # country = await Country.get(country=data.country)
            # print(country)
            query = f"SELECT * FROM public.airports WHERE iata = '{queryparams.get('iata')}'"
            result, _ = await conn.queryrow(query)
            if result:
                print(result)
        print('DATA > ', data)
        print('QS ', queryparams)
        return data

    async def _put_response(self, result, status = 200, fields = None):
        return await super()._put_response(result, status, fields)

    async def _get_callback(self, response: web.Response, result, *args, **kwargs):
        await asyncio.sleep(3)
        print('GET CALLBACK', result)
        return response

    async def _post_callback(self, response: web.Response, result, *args, **kwargs):
        print('POST CALLBACK', result)
        return response

    async def _put_callback(self, response: web.Response, result, *args, **kwargs):
        print('PUT CALLBACK', result)
        return response

    async def _patch_callback(self, response: web.Response, result, *args, **kwargs):
        print('PATCH CALLBACK', result)
        return response



    def required_by_put(self, *args, **kwargs):
        return True

    async def _set_created_by(self, value, column, **kwargs):
        return await self.get_userid(session=self._session)

    async def _put_callback(self, response: web.Response, result, *args, **kwargs):
        print('RESULT > ', result)
        print('RESPONSE > ', response)
        print('PUT CALLBACK')
        return response

    _post_callback = _put_callback

    async def on_startup(self, *args, **kwargs):
        print(args, kwargs)
        print('THIS CODE RUN ON STARTUP')

    async def on_shutdown(self, *args, **kwargs):
        print('ESTO OCURRE CUANDO SE DETIENE ==== ')

## two required handlers for a ModelHandler.
AirportHandler.configure(app, '/api/v1/airports')

async def start_example(db):
    """
    Create the Table:
    """
    await db.connect()
    async with await db.acquire() as conn:
        table = """
        DROP TABLE IF EXISTS public.airports;
        CREATE TABLE IF NOT EXISTS public.airports
        (
         iata character varying(3),
         airport character varying(60),
         city character varying(20),
         airport_type integer,
         country character varying(30),
         created_by integer,
         created_at timestamp with time zone NOT NULL DEFAULT now(),
         CONSTRAINT pk_airports_pkey PRIMARY KEY (iata)
        )
        WITH (
        OIDS=FALSE
        );
        """
        await conn.execute(table)
        ### create some airports:
        print(' == TEST Bulk Insert == ')
        Airport.Meta.connection = conn
        data = [
            {
                "iata": "AEP", "airport": "Jorge Newbery", "city": "Buenos Aires",
                "country": "Argentina", "created_by": 35
            },
            {
                "iata": "ADL", "airport": "Adelaide International", "city": "Adelaide",
                "country": "Australia", "created_by": 35
            },
            {
                "iata": "BSB", "airport": "President Juscelino Kubitschek", "city": "Brasilia",
                "country": "Brasil", "created_by": 35
            },
            {
                "iata": "GRU", "airport": "São Paulo-Guarulhos", "city": "Sao Paulo",
                "country": "Brasil", "created_by": 35
            },
            {
                "iata": "CCS", "airport": "Simon Bolívar Maiquetia", "city": "Caracas",
                "country": "Venezuela", "created_by": 35
            },
        ]
        await Airport.create(data)
    # await db.release(conn)


async def end_example(db):
    """
    DROP the Table:
    """
    async with await db.acquire() as conn:
        drop = "DROP TABLE IF EXISTS public.airports;"
        result = await conn.execute(drop)
        logging.debug(f'DELETE {result}')


if __name__ == "__main__":
    params = {
        "user": "troc_pgdata",
        "password": "12345678",
        "host": "127.0.0.1",
        "port": "5432",
        "database": "pruebas",
        "DEBUG": True,
    }
    kwargs = {
        "server_settings": {
            'client_min_messages': 'notice',
            'max_parallel_workers': '24',
            'tcp_keepalives_idle': '30'
        }
    }
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        pool = AsyncPool("pg", params=params, loop=loop, **kwargs)
        app['database'] = pool
        loop.run_until_complete(
            start_example(pool)
        )
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(
            end_example(pool)
        )
        loop.close()
