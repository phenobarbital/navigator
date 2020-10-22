#!/usr/bin/env python
import asyncio
import json
from functools import wraps
from pathlib import Path

from aiohttp import WSCloseCode, WSMsgType, web
from aiohttp.http_exceptions import HttpBadRequest
from aiohttp.web import Request, Response
from aiohttp.web_exceptions import HTTPMethodNotAllowed
from aiohttp_swagger import *

from navigator.conf import BASE_DIR


def callback_channel(ws):
    def listen(connection, pid, channel, payload):
        print("Running Callback Channel for {}: {}".format(channel, payload))
        asyncio.ensure_future(ws.send_str(payload))

    return listen


async def channel_handler(request):
    channel = request.match_info.get("channel", "navigator")
    print("Websocket connection starting for channel {}".format(channel))
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    socket = {"ws": ws, "conn": connection}
    request.app["websockets"].append(socket)
    print(socket)
    try:
        async for msg in ws:
            pass
    finally:
        request.app["websockets"].remove(socket)
    return ws


class WebSocket(web.View):
    def __init__(self, *args, **kwargs):
        super(WebSocket, self).__init__(*args, **kwargs)
        self.app = self.request.app

    async def get(self):
        # user need a channel:
        channel = self.request.match_info.get("channel", "navigator")
        print("Websocket connection starting")
        ws = web.WebSocketResponse()
        await ws.prepare(self.request)
        self.request.app["websockets"].append(ws)
        print("Websocket connection ready")
        # ws.start(request)
        # session = await get_session(self.request)
        # user = User(self.request.db, {'id': session.get('user')})
        # login = await user.get_login()
        try:
            async for msg in ws:
                print(msg)
                if msg.type == WSMsgType.TEXT:
                    print(msg.data)
                    if msg.data == "close":
                        await ws.close()
                    else:
                        await ws.send_str(msg.data + "/answer")
                elif msg.type == WSMsgType.ERROR:
                    print("ws connection closed with exception %s" % ws.exception())
        finally:
            self.request.app["websockets"].remove(ws)

        print("Websocket connection closed")
        return ws


async def ping(request):
    """
    ---
    summary: This end-point allow to test that service is up.
    tags:
    - Health check
    produces:
    - text/plain
    responses:
        "200":
            description: successful operation. Return "pong" text
        "405":
            description: invalid HTTP Method
    """
    return web.Response(text="pong")


async def home(request):
    """
    ---
    summary: This end-point is the default "home" for all newly projects
    tags:
    - Home
    - Index
    produces:
    - text/html
    responses:
        "200":
            description: template "templates/home.html" returned.
        "404":
            description: Template "templates/home.html" not found.
    """
    path = Path(BASE_DIR).joinpath("templates/home.html")
    try:
        file_path = path
        if not file_path.exists():
            return web.HTTPNotFound()
        return web.FileResponse(file_path)
    except Exception as e:
        response_obj = {"status": "failed", "reason": str(e)}
        return web.Response(
            text=json.dumps(response_obj), status=500, content_type="application/json"
        )
