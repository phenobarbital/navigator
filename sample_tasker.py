import asyncio
import time
from functools import partial
from aiohttp import web
from navconfig.logging import logging
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse
from navigator.background import SERVICE_NAME, BackgroundQueue, BackgroundTask

# Middleware to print request details
@web.middleware
async def debug_middleware(request, handler):
    app = request.app
    for route in app.router.routes():
        logging.debug(
            f"Route added: {route.resource}, method: {route.method}, Path: {route.resource.canonical}"
        )
    logging.debug(
        f"Request received: {request.method} {request.path}"
    )
    match_info = request.match_info
    logging.debug(f"Matched info: {match_info}")
    response = await handler(request)
    return response

app = Application(
    middlewares=[debug_middleware]
)

auth = AuthHandler()
auth.setup(app)  # configure this Auth system into App.

# Background Queue:
BackgroundQueue(app=app, max_workers=5, queue_size=5, enable_profiling=True)

@app.get('/')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(body="Hola Mundo")


async def send_email(email, message):
    print(' :: Waiting for 10 seconds to finish task :: ')
    await asyncio.sleep(10)  # Simulate email sending
    print(f"Email sent to {email} with message: {message}")

def blocking_code(request):
    time.sleep(10)
    print(":: Blocking code executed ::")

def blocking_task(request):
    print(':: STARTS BLOCKING CODE ::')
    time.sleep(10)
    print(":: Blocking TASK executed ::")

async def handle_post(request):
    data = await request.json()
    tasker = request.app[SERVICE_NAME]
    await tasker.put(send_email, data['email'], data['message'])
    fn = partial(blocking_code, request)
    await tasker.put(fn)
    # Using Background Task Runner:
    task = BackgroundTask(blocking_task, request)
    asyncio.create_task(task.run())
    return web.json_response({'status': 'Task enqueued'})


app.router.add_post('/manage_tasks', handle_post)

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        pass
