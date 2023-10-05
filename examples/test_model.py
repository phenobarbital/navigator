from typing import Union
import asyncio
from datetime import datetime
from aiohttp import web
from navconfig.logging import logging
from asyncdb import AsyncPool
from asyncdb.models import Model, Column
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse
from navigator.views import ModelView


class Country(Model):
    country_code: str = Column(primary_key=True)
    country: str
class Airport(Model):
    iata: str = Column(primary_key=True, required=True, label='IATA Code')
    airport: str = Column(required=True, label="Airport Name")
    city: str
    country: str
    created_by: int
    created_at: datetime = Column(default=datetime.now(), repr=False)

    class Meta:
        name: str = 'airports'
        schema = 'public'
        strict = True


app = Application()
session = AuthHandler()
session.setup(app)

@app.get('/hello')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(content="<h1>Hello Airport</h1>")


class AirportHandler(ModelView):
    model: Model = Airport
    pk: Union[str, list] = ['iata']

    async def _get_created_by(self, value, column, **kwargs):
        return await self.get_userid(session=self._session)

    # async def on_startup(self, *args, **kwargs):
    #     print(args, kwargs)
    #     print('THIS CODE RUN ON STARTUP')

    # async def on_shutdown(self, *args, **kwargs):
    #     print('ESTO OCURRE CUANDO SE DETIENE ==== ')

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
    await db.release(conn)


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
        "database": "navigator_dev",
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
