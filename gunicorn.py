#!/usr/bin/env python3
import sys
import asyncio
import uvloop
from aiohttp import web
from navigator import Application, Response
from app import Main

asyncio.set_event_loop_policy(
    uvloop.EventLoopPolicy()
)


async def navigator():
    app = Application(Main)
    # Enable WebSockets Support
    app.add_websockets()
    return app
