from typing import Union
import asyncio
from datetime import datetime
from aiohttp import web
from asyncdb import AsyncPool
from asyncdb.models import Model, Column
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse
from navigator.views import ModelHandler

class Airport(Model):
    iata: str = Column(primary_key=True, required=True)
    airport: str
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


class AirportHandler(ModelHandler):
    model: Model = Airport
    pk: Union[str, list] = 'iata'

    async def _get_created_by(self, value, column, **kwargs):
        return await self.get_userid(session=self._session)

## two required handlers for a ModelHandler.
app.router.add_view(r"/api/v1/airports/{id:.*}", AirportHandler)
app.router.add_view(r'/api/v1/airports{meta:\:?.*}',AirportHandler)

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
            {"iata": "AEP", "airport": "Jorge Newbery", "city": "Buenos Aires", "country": "Argentina"},
            {"iata": "ADL", "airport": "Adelaide International", "city": "Adelaide", "country": "Australia"},
            {"iata": "BSB", "airport": "President Juscelino Kubitschek", "city": "Brasilia", "country": "Brasil"},
            {"iata": "GRU", "airport": "São Paulo-Guarulhos", "city": "Sao Paulo", "country": "Brasil"},
            {"iata": "CCS", "airport": "Simon Bolívar Maiquetia", "city": "Caracas", "country": "Venezuela"},
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
        print(result)
    # await db.wait_close(timeout=5)


if __name__ == "__main__":
    params = {
        "user": "troc_pgdata",
        "password": "12345678",
        "host": "127.0.0.1",
        "port": "5432",
        "database": "navigator",
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
        loop = asyncio.get_event_loop()
        pool = AsyncPool(
            "pg",
            params=params,
            loop=loop,
            **kwargs
        )
        app['database'] = pool
        loop.run_until_complete(
            start_example(pool)
        )
        print('=== START APP === ')
        app.run()
    except KeyboardInterrupt:
        print(' == CLOSING APP == ')
        print('== DELETE TABLE ==')
        loop.run_until_complete(
            end_example(pool)
        )
