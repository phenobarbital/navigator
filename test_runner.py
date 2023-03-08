import asyncio
import uvloop
from aiohttp import web
# from app import Main
from navigator import Application



async def navigator():
    host = 'localhost'
    port = 5000
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    uvloop.install()
    app = Application()
    runner = web.AppRunner(
        app.setup()
    )
    await runner.setup()
    site = web.TCPSite(
        runner,
        host,
        port,
        backlog=5,
        reuse_port=True
    )
    await site.start()
    print(f"Serving up app on {host}:{port}")
    return runner, site


loop = asyncio.get_event_loop()
runner, site = loop.run_until_complete(navigator())
try:
    loop.run_forever()
except KeyboardInterrupt as err:
    loop.run_until_complete(runner.cleanup())
