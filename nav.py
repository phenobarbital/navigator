import asyncio
import uvloop
from aiohttp import web
from asyncdb import AsyncDB
from asyncdb.exceptions import DriverError, ProviderError
from navigator import Application
from navigator.responses import JSONResponse
from navigator.conf import default_dsn
from app import Main

# async def hola(request: web.Request, *args, **kwargs) -> web.Response:
#     return Response('Hola Mundo')

# async def index(request):
#     return Response(text='Welcome home!')
async def sample(request: web.Request) -> web.Response:
    try:
        db = AsyncDB('pg', dsn=default_dsn)
        async with await db.connection() as conn:
            result, _ = await conn.query(
                'select sales_id, store_id, store_name, account_name, sale_class, sale_subclass, material from epson.sales limit 10000'
            )
            data = [dict(x) for x in result]
    except (DriverError, ProviderError) as err:
        print(err)
    return JSONResponse(data, status=200)

async def navigator():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    uvloop.install()
    # define new Application
    app = Application(Main, enable_jinja2=True)
    # Enable WebSockets Support
    # app.add_websockets()
    app.router.add_route('GET', '/sample', sample)
    # app.router.add_route('GET', '/hola', hola)
    # returns App.
    return app.setup()
    # return app
