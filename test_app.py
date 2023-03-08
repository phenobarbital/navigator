#!/usr/bin/env python3
from aiohttp import web
from asyncdb import AsyncDB
from asyncdb.exceptions import DriverError, ProviderError
from navigator import Application
from navigator.responses import JSONResponse
from navigator.conf import default_dsn
from app import Main

# define a new Application
app = Application(app=Main)

# Enable WebSockets Support
# app.add_websockets()

@app.get('/sample')
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


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
