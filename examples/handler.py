import asyncio
from aiohttp import web
from navigator import Application
from navigator.background import BackgroundQueue, TaskWrapper
from app import Main


async def blocking_code(*args, **kwargs):
    print('Starting blocking code')
    await asyncio.sleep(10)  # Simulate a blocking operation
    print('Finished blocking code')

async def done_blocking(*args, **kwargs):
    print('Done Blocking Code :::')

async def handle(request):
    name = request.match_info.get('name', "Anonymous")
    text = f"Hello, {name}"
    queue = request.app['service_queue']
    try:
        task = TaskWrapper(
            fn=blocking_code,
            args=(name,),
            kwargs={'text': text}
        )
        task.add_callback(done_blocking)
        print('Adding task to queue:', task)
        await queue.put(task)
    except asyncio.QueueFull:
        text = "Queue is full, please try again later."
        print(text)
    except Exception as e:
        text = f"An error occurred: {str(e)}"
        print(text)
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
