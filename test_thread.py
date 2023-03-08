import sys
import asyncio
import threading
import uvloop
from aiohttp import web
from navigator import Application


def navigator_service():
    app = Application()
    runner = web.AppRunner(app.setup())
    return runner

def run_server(runner):
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    uvloop.install()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, 'localhost', 5000)
    loop.run_until_complete(site.start())
    loop.run_forever()
    # yield
    # loop.run_until_complete(runner.cleanup())


if __name__ == '__main__':
    try:
        t = threading.Thread(target=run_server, args=(navigator_service(),))
        t.start()
    except KeyboardInterrupt:
        sys.exit(0)
