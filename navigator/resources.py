#!/usr/bin/env python
import asyncio
from collections.abc import Callable
import random
import uuid
from pathlib import Path
import aiohttp
from aiohttp import WSMsgType, web
from navconfig import BASE_DIR
from navconfig.logging import logging, logger
from navigator_session import get_session
from .libs.json import json_encoder


async def register_closing_ws(self, app: web.Application):
    """
    Register closing sockets on app shutdown.
    """
    sockets = app.get("sockets", [])
    close_tasks = []
    for socket in sockets:
        ws = socket["ws"]
        if not ws.closed:
            logger.debug("Closing a websocket connection.")
            close_tasks.append(ws.close())
    # Wait for all websocket connections to close.
    if close_tasks:
        await asyncio.gather(*close_tasks)

async def channel_handler(
    request: web.Request,
    append_callback: Callable = None,
    receive_callback: Callable = None,
    disconnect_callback: Callable = None
):
    """
    Handles a WebSocket connection for a given channel.
    """
    channel = request.match_info.get("channel", "navigator")
    logger.debug(
        f"Websocket connection starting for channel {channel}"
    )
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    socket = {"ws": ws}
    # Register the socket
    try:
        request.app["sockets"].append(socket)
    except KeyError:
        request.app["sockets"] = [socket]

    if append_callback:
        await append_callback(socket)

    # Notify all connected clients
    for client in request.app["sockets"]:
        await client["ws"].send_str("Someone joined")
    logger.debug(f"WS Channel :: {channel} :: connection ready")

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data == "close":
                    await ws.close()
                else:
                    if receive_callback:
                        await receive_callback(socket, msg)
                    await ws.send_str(f"{msg.data}/answer")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(
                    f"WS connection closed with exception {ws.exception()}"
                )
    except asyncio.CancelledError:
        # Handle cancellation if needed
        pass
    finally:
        if socket in request.app["sockets"]:
            request.app["sockets"].remove(socket)
        if disconnect_callback:
            await disconnect_callback(socket)
        for client in request.app["sockets"]:
            await client["ws"].send_str("Someone disconnected.")
    return ws


async def ping(request: web.Request):
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
    return web.Response(text="PONG")


async def home(request: web.Request):
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
            return web.HTTPNotFound(
                reason="Template not found: navigator/templates/home.html"
            )
        return web.FileResponse(file_path)
    except Exception as e:  # pylint: disable=W0703
        response_obj = {"status": "failed", "reason": str(e)}
        return web.Response(
            text=json_encoder(response_obj), status=500, content_type="application/json"
        )

class WebSocketHandler(web.View):
    channels: dict = {}
    clients = {}   # Map WebSocket to client ID
    usernames = set()    # Keeps track of active usernames
    clients_lock = asyncio.Lock()  # Ensures thread-safe access to shared data

    def __init__(self, request: web.Request) -> None:
        super().__init__(request)
        self.app = self.request.app
        self.logger = logging.getLogger('Nav.WebSocket')
        self.logger.setLevel(logging.DEBUG)
        self.logger.notice(':: Started WebSocket Handler ::')

    async def get(self):
        # user need a channel:
        channel = self.request.match_info.get("channel", "navigator")
        self.logger.debug(
            f"Websocket connection starting to {channel!s}"
        )
        try:
            ws = web.WebSocketResponse()
            await ws.prepare(self.request)

            client_id = str(uuid.uuid4())  # Generate a unique client ID
            session = await get_session(self.request)
            if session and 'username' in session:
                username = session['username']
            else:
                username = self.request.query.get('username', f'User{client_id[:5]}')

            # Ensure the username is unique among connected clients
            async with self.clients_lock:
                initial_username = username
                while username in self.usernames:
                    random_number = random.randint(1, 9999)
                    username = f"{initial_username}{random_number}"
                self.clients[ws] = username
                self.usernames.add(username)

            # Add WebSocket to the channel
            if channel not in self.channels:
                self.channels[channel] = []
            self.channels[channel].append(ws)

            await ws.send_str(f'Your username is: {username}')

            self.logger.debug(
                f"Client {username} Connected to Channel: {channel!s}"
            )

            # Send "someone joined" message to all clients in the channel
            await self.broadcast(
                channel,
                f'Client {username} joined the channel',
                exclude_ws=ws
            )
        except Exception as e:
            self.logger.exception(
                f"An error occurred in WebSocketHandler.get: {e}"
            )
            return web.Response(
                status=500,
                text='Internal Server Error on WebSocketHandler'
            )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Broadcast the message to all clients in the channel
                    if msg.data == 'close':
                        await ws.close()
                    else:
                        await self.broadcast(channel, f':: {username}: {msg.data}')
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(
                        f'WebSocket connection closed with exception {ws.exception()}'
                    )
        finally:
            # Remove WebSocket from the channel on disconnect
            self.channels[channel].remove(ws)
            self.logger.info(f'Client {username} from channel: {channel}')
            # Send "someone left" message to all clients in the channel
            await self.broadcast(
                channel,
                f'Client {username} left the channel',
                exclude_ws=ws
            )

            # Remove the username and WebSocket from tracking
            async with self.clients_lock:
                del self.clients[ws]
                self.usernames.remove(username)

        return ws

    async def broadcast(self, channel, message, exclude_ws=None):
        for ws in self.channels.get(channel, []):
            if ws is not exclude_ws and not ws.closed:
                await ws.send_str(message)
