import asyncio
from aiohttp import web
from navigator import Application
from navigator.background import BackgroundQueue
from app import Main


async def blocking_code():
    print('Starting blocking code')
    await asyncio.sleep(5)
    print('Finished blocking code')

async def done_blocking(*args, **kwargs):
    print('Done Blocking Code :::')

async def handle(request):
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    queue = request.app['service_queue']
    # future = asyncio.create_task(blocking_code())
    await queue.put(blocking_code)
    # queue.add_callback(done_blocking)
    return web.Response(text=text)

app = Application()

BackgroundQueue(
    app=app,
    max_workers=2,
    queue_size=4
)

app.add_routes([web.get('/', handle),
                web.get('/{name}', handle)])


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
