#!/usr/bin/env python
import asyncio
import json
from functools import wraps
from pathlib import Path
import logging
import aiohttp
from aiohttp import WSCloseCode, WSMsgType, web, web_urldispatcher
from aiohttp.http_exceptions import HttpBadRequest
from aiohttp.web import Request, Response
from aiohttp.web_exceptions import HTTPMethodNotAllowed
from aiohttp_swagger import *
from navigator_session import get_session
from navigator.conf import BASE_DIR


class Router(web.UrlDispatcher):
    async def resolve(self, request):
        res = await super().resolve(request)
        if isinstance(res, web_urldispatcher.MatchInfoError):
            if res.http_exception.status == 404:
                url = str(request.rel_url)
                if '/authorize' in url:
                    authorization = {
                        "status": "Tenant Authorized",
                        "program": 'Navigator'
                    }
                    return web_urldispatcher.MatchInfoError(
                        web.HTTPAccepted(
                            reason=authorization,
                            content_type='application/json'
                        )
                    )
                else:
                    return web_urldispatcher.MatchInfoError(
                        web.HTTPNotFound()
                    )
        return res


async def channel_handler(request):
    channel = request.match_info.get("channel", "navigator")
    logging.debug(f"Websocket connection starting for channel {channel}")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    # TODO: connection is not defined, I dont understand this code
    # socket = {"ws": ws, "conn": connection}
    try:
        socket = {"ws": ws}
        try:
            request.app["sockets"].append(socket)
        except KeyError:
            request.app["sockets"] = []
            request.app["sockets"].append(socket)
        print(socket)
        logging.debug(f"WS Channel :: {channel} :: connection ready")
    except asyncio.CancelledError:
        request.app['sockets'].remove(socket)
        for ws in request.app['sockets']:
            await ws.send_str('Someone disconnected.')
    try:
        async for msg in ws:
            print(msg)
            if msg.type == aiohttp.WSMsgType.TEXT:
                print(msg.data)
                if msg.data == "close":
                    await ws.close()
                else:
                    await ws.send_str(msg.data + "/answer")
    finally:
        request.app["sockets"].remove(socket)
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

        for _ws in self.request.app["sockets"]:
            _ws.send_str(f'Someone Joined.')

        self.request.app["sockets"].append(ws)
        session = await get_session(self.request)
        if session:
            session['socket'] = ws
        print("Websocket connection ready")
        async for msg in ws:
            print(msg)
            if msg.type == WSMsgType.TEXT:
                if msg.data == "close":
                    await ws.close()
                else:
                    print(msg.data)
                    await ws.send_str(msg.data + "/answer")
            elif msg.type == WSMsgType.ERROR:
                exp = ws.exception()
                logging.error(f"ws connection closed with exception {exp}")
            else:
                pass
        self.request.app["sockets"].remove(ws)
        session['socket'] = None
        for _ws in self.request.app["sockets"]:
            _ws.send_str(f'Someone Disconnected.')
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
    path = Path(BASE_DIR).joinpath("navigator/templates/home.html")
    try:
        file_path = path
        if not file_path.exists():
            return web.HTTPNotFound()
        return web.FileResponse(file_path)
    except Exception as e:
        response_obj = {"status": "failed", "reason": str(e)}
        return web.Response(
            text=json.dumps(response_obj),
            status=500,
            content_type="application/json"
        )
