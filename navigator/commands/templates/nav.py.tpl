import asyncio
import uvloop
from navigator import Application
from app import Main


async def navigator():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    uvloop.install()
    # define new Application
    app = Application(Main, enable_jinja2=True)
    # Enable WebSockets Support
    app.add_websockets()
    return app.setup()
