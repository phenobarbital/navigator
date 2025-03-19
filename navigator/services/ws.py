from typing import Dict, List, Any, Optional, Union, Set
from collections.abc import Callable
import asyncio
import random
import uuid
import orjson
from navconfig.logging import logging, logger
import aiohttp
from aiohttp import WSMsgType, web
from navigator_session import get_session
from ..libs.json import json_encoder, json_decoder
from ..types import WebApp
from ..applications.base import BaseApplication

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


class WebSocketChannelManager:
    """WebSocketChannelManager.

    WebSocketChannelManager is a class that manages websocket connections.

    Usage:
    ```python
    from aiohttp import web
    from navigator.services.ws import WebSocketChannelManager

    app = web.Application()
    ws_manager = WebSocketChannelManager(app, route_prefix='/ws')

    async def on_client_connect(ws, channel, client_info):
        print(f"Client connected to {channel}: {client_info}")

    async def on_client_disconnect(ws, channel, client_info):
        print(f"Client disconnected from {channel}: {client_info}")

    async def on_client_message(ws, channel, msg_type, msg_data):
        print(f"Message in {channel}: {msg_type} - {msg_data}")

    # Register the callbacks
    ws_manager.add_connect_callback("default", on_client_connect)
    ws_manager.add_message_callback("default", on_client_message)
    ws_manager.add_disconnect_callback("default", on_client_disconnect)

    """
    _prefix: str = 'ws'

    def __init__(
        self,
        app: web.Application,
        prefix: Optional[str] = None,
        route_prefix: Optional[str] = '/ws'
    ):
        """Initialize the WebSocketChannelManager."""
        if prefix:
            self._prefix = prefix
        self.app = app
        self.channels: Dict[str, List[Dict[str, Any]]] = {}
        self.on_connect_callbacks: Dict[str, List[Callable]] = {}
        self.on_message_callbacks: Dict[str, List[Callable]] = {}
        self.on_disconnect_callbacks: Dict[str, List[Callable]] = {}

        # Set up app cleanup
        self.app.on_shutdown.append(self._on_shutdown)

        # Setup a Route:
        self.app.router.add_get(
            f'{route_prefix}/{{channel}}', self.handle_websocket)
        self.app.router.add_get(
            route_prefix, self.handle_websocket
        )  # Default channel

    async def _on_shutdown(self, app):
        """Close all websocket connections when the app is shutting down."""
        for channel, sockets in self.channels.items():
            for socket in sockets:
                await socket[self._prefix].close(
                    code=1001,
                    message="Server shutdown"
                )

    def register_channel(self, channel_name: str):
        """Register a new channel if it doesn't exist."""
        if channel_name not in self.channels:
            self.channels[channel_name] = []
            self.on_connect_callbacks[channel_name] = []
            self.on_message_callbacks[channel_name] = []
            self.on_disconnect_callbacks[channel_name] = []

    def add_connect_callback(self, channel: str, callback: Callable):
        """Add a callback for when a client connects to the channel."""
        if channel not in self.on_connect_callbacks:
            self.register_channel(channel)
        self.on_connect_callbacks[channel].append(callback)

    def add_message_callback(self, channel: str, callback: Callable):
        """Add a callback for when a message is received on the channel."""
        if channel not in self.on_message_callbacks:
            self.register_channel(channel)
        self.on_message_callbacks[channel].append(callback)

    def add_disconnect_callback(self, channel: str, callback: Callable):
        """Add a callback for when a client disconnects from the channel."""
        if channel not in self.on_disconnect_callbacks:
            self.register_channel(channel)
        self.on_disconnect_callbacks[channel].append(callback)

    async def broadcast_to_channel(
        self,
        channel: str,
        message: Union[str, dict, bytes],
        exclude_ws=None
    ):
        """Broadcast a message to all clients in a channel, optionally excluding one."""
        if channel not in self.channels:
            return

        for socket in self.channels[channel]:
            if exclude_ws and socket[self._prefix] == exclude_ws:
                continue

            if isinstance(message, dict):
                message_str = json_encoder(message)
                await socket[self._prefix].send_str(message_str)
            elif isinstance(message, str):
                await socket[self._prefix].send_str(message)
            elif isinstance(message, bytes):
                await socket[self._prefix].send_bytes(message)

    async def handle_websocket(self, request: web.Request):
        """Handle a websocket connection for a specific channel."""
        channel = request.match_info.get("channel", "default")
        logging.debug(f"Websocket connection starting for channel {channel}")

        # Register the channel if it doesn't exist
        if channel not in self.channels:
            self.register_channel(channel)

        # Set up the websocket
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Create a socket object
        socket = {"ws": ws, "request": request, "id": id(ws)}

        try:
            # Add the socket to the channel
            self.channels[channel].append(socket)

            # Call the on_connect callbacks
            client_info = {
                "ip": request.remote,
                "headers": dict(request.headers)
            }
            for callback in self.on_connect_callbacks[channel]:
                await asyncio.create_task(callback(ws, channel, client_info))

            # Process messages
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        # Try to parse as JSON first
                        data = json_decoder(msg.data)
                        msg_type = data.get("type", "message")
                        msg_data = data.get("data", {})
                    except orjson.JSONDecodeError:
                        # Fallback to treating it as plain text
                        msg_type = "text"
                        msg_data = msg.data

                    # Handle special commands
                    if isinstance(msg_data, str) and msg_data.lower() == "close":
                        await ws.close()
                        break

                    # Call the on_message callbacks
                    results = []
                    for callback in self.on_message_callbacks[channel]:
                        result = await asyncio.create_task(callback(ws, channel, msg_type, msg_data))
                        if result:
                            results.append(result)

                    # Send the response if no callback explicitly handled it
                    if not any(r is True for r in results):
                        if isinstance(msg_data, str):
                            await ws.send_str(f"Received: {msg_data}")
                        else:
                            response = {"type": "response", "data": msg_data}
                            await ws.send_str(json_encoder(response))

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error(
                        f"WebSocket connection closed with exception: {ws.exception()}"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    for callback in self.on_message_callbacks[channel]:
                        await asyncio.create_task(callback(ws, channel, "binary", msg.data))
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    break

        except asyncio.CancelledError:
            logging.debug(
                f"WebSocket connection cancelled in channel {channel}"
            )
        finally:
            # Remove the socket from the channel
            if socket in self.channels[channel]:
                self.channels[channel].remove(socket)

            # Call the on_disconnect callbacks
            for callback in self.on_disconnect_callbacks[channel]:
                await asyncio.create_task(callback(ws, channel, {"id": socket["id"]}))

            # Notify other clients in the channel
            await self.broadcast_to_channel(
                channel,
                {
                    "type": "system",
                    "data": "A user has disconnected"
                },
                exclude_ws=ws
            )

        return ws


class WebSocketHandler(web.View):
    """WebSocketHandler.

    WebSocketHandler is a class that handles websocket connections.
    """
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


class WebSocketView(web.View):
    """
    WebSocket View that uses the WebSocketManager.
    This provides a class-based approach for handling WebSockets.
    """
    async def get(self):
        ws_manager = self.request.app['ws_manager']
        return await ws_manager.handle_websocket(self.request)

class WebSocketManager:
    """
    WebSocket Manager that handles multi-channel communication,
    user management, and event callbacks.
    """
    _app_prefix: str = 'ws_manager'

    def __init__(self, app: web.Application, route_prefix: str = '/websockets'):
        if isinstance(app, BaseApplication):
            self.app = app.get_app()
        elif isinstance(app, WebApp):
            self.app = app
        self.logger = logging.getLogger('WebSocketManager')
        self.route_prefix = route_prefix

        # Channels and clients management
        self.channels: Dict[str, List[web.WebSocketResponse]] = {}
        self.clients: Dict[web.WebSocketResponse, Dict[str, Any]] = {}
        self.usernames: Set[str] = set()
        self.clients_lock = asyncio.Lock()

        # Event callbacks
        self.on_connect_callbacks: Dict[str, List[Callable]] = {}
        self.on_message_callbacks: Dict[str, List[Callable]] = {}
        self.on_disconnect_callbacks: Dict[str, List[Callable]] = {}
        self.on_direct_message_callbacks: Dict[str, List[Callable]] = {}  # For direct messages

        # Register onstartup/shutdown handler
        app.on_startup.append(self._on_startup)

        # Register on shutdown handler
        app.on_cleanup.append(self._on_cleanup)
        app.on_shutdown.append(self._on_shutdown)

        # Register into app
        self.app['ws_manager'] = self
        # Set up routes
        # Function-based approach
        self.app.router.add_get(
            f'{self.route_prefix}/{{channel}}',
            self.handle_websocket
        )
        self.app.router.add_get(
            f'{self.route_prefix}',
            self.handle_websocket
        )

        self.logger.info(
            ':: WebSocket Manager initialized ::'
        )

    async def _on_startup(self, app: web.Application):
        """Register for startup Information."""
        pass

    async def _on_cleanup(self, app: web.Application):
        """Hook for cleanup actions. Override in subclasses for custom behavior."""
        self.logger.info(
            'WebSocket Manager cleaning up'
        )

    async def _on_shutdown(self, app: web.Application):
        """Close all websockets when the application is shutting down."""
        self.logger.info('Shutting down all WebSocket connections')
        close_tasks = []

        for _, websockets in self.channels.items():
            close_tasks.extend(
                ws.close(code=1001, message=b'Server shutdown')
                for ws in websockets
                if not ws.closed
            )

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

    def register_channel(self, channel_name: str):
        """Register a new channel if it doesn't exist."""
        if channel_name not in self.channels:
            self.channels[channel_name] = []
            self.on_connect_callbacks[channel_name] = []
            self.on_message_callbacks[channel_name] = []
            self.on_direct_message_callbacks[channel_name] = []
            self.on_disconnect_callbacks[channel_name] = []

    def register_connect_callback(self, channel: str, callback: Callable):
        """Register a callback for client connection events."""
        if channel not in self.on_connect_callbacks:
            self.register_channel(channel)
        self.on_connect_callbacks[channel].append(callback)

    def register_message_callback(self, channel: str, callback: Callable):
        """Register a callback for message events."""
        if channel not in self.on_message_callbacks:
            self.register_channel(channel)
        self.on_message_callbacks[channel].append(callback)

    def register_disconnect_callback(self, channel: str, callback: Callable):
        """Register a callback for client disconnection events."""
        if channel not in self.on_disconnect_callbacks:
            self.register_channel(channel)
        self.on_disconnect_callbacks[channel].append(callback)

    def register_direct_message_callback(self, channel: str, callback: Callable):
        """
        Register a callback for direct message events.

        Callback signature: async def callback(ws, sender_info, recipient, msg_content)
        """
        if channel not in self.on_direct_message_callbacks:
            self.register_channel(channel)
        self.on_direct_message_callbacks[channel].append(callback)

    async def broadcast(self, channel: str, message: Union[str, dict], exclude_ws=None):
        """Broadcast a message to all clients in a channel."""
        if channel not in self.channels:
            return

        message_str = message if isinstance(message, str) else json_encoder(message)

        for ws in self.channels[channel]:
            if ws is not exclude_ws and not ws.closed:
                await ws.send_str(message_str)

    async def broadcast_to_users(self, channel: str, usernames: List[str], message: Union[str, dict]):
        """Send a message to specific users in a channel."""
        if channel not in self.channels:
            return

        message_str = message if isinstance(message, str) else json_encoder(message)

        for ws in self.channels[channel]:
            if not ws.closed and self.clients.get(ws, {}).get('username') in usernames:
                await ws.send_str(message_str)

    async def send_to_user(self, username: str, message: Union[str, dict], sender_info=None):
        """
        Send a direct message to a specific user across all channels.

        Args:
            username: The username of the recipient
            message: The message to send
            sender_info: Optional information about the sender

        Returns:
            tuple: (bool success, recipient_ws or None)
        """
        message_str = message if isinstance(message, str) else json_encoder(message)

        for ws, client_info in self.clients.items():
            if not ws.closed and client_info.get('username') == username:
                await ws.send_str(message_str)
                return True, ws
        return False, None

    async def get_channel_users(self, channel: str) -> List[str]:
        """Get a list of usernames in a specific channel."""
        if channel not in self.channels:
            return []

        return [
            self.clients.get(ws, {}).get('username') for ws in self.channels[channel] if not ws.closed
        ]

    async def on_connect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        client_info: Dict[str, Any],
        session: Dict
    ):
        """Method called when a client connects to the channel."""
        pass

    async def _on_connect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        username: str,
        client_info: Dict[str, Any],
        session: Dict
    ):
        """Internal method to handle client connection events."""
        try:
            await self.on_connect(ws, channel, client_info, session)
        except Exception as e:
            self.logger.error(
                f"Error in on_connect method: {e}"
            )
        # Execute on_connect callbacks
        for callback in self.on_connect_callbacks.get(channel, []):
            try:
                await asyncio.create_task(callback(ws, channel, client_info))
            except Exception as e:
                self.logger.error(
                    f"Error in on_connect callback: {e}"
                )
        # Announce new user to channel
        await self.broadcast(
            channel,
            {
                'type': 'system',
                'event': 'user_joined',
                'data': {
                    'username': username,
                    'channel': channel
                }
            },
            exclude_ws=ws
        )

    async def on_direct(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        target: str,
        direct_msg: dict,
        client_info: Dict[str, Any]
    ):
        """Method called when a direct message is received."""
        pass

    async def _on_direct(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        target: str,
        direct_msg: dict,
        sender_info: Dict[str, Any]
    ):
        """Internal method to handle direct message events."""
        success, recipient_ws = await self.send_to_user(
            target,
            direct_msg,
            sender_info=self.clients[ws]
        )

        if not success:
            await ws.send_str(json_encoder({
                'type': 'error',
                'message': f'User {target} not found or offline'
            }))
            return False

        # Calling the "OnDirect" Method:
        try:
            await self.on_direct(
                ws,
                channel,
                target,
                direct_msg,
                sender_info
            )
        except Exception as e:
            self.logger.error(
                f"Error in on_direct method: {e}"
            )

        # Execute direct message callbacks
        for callback in self.on_direct_message_callbacks.get(channel, []):
            try:
                # Pass ws, sender info, recipient username, and message content
                await asyncio.create_task(
                    callback(
                        ws,
                        self.clients[ws],
                        target,
                        direct_msg.get('msg_content'),
                        recipient_ws
                    )
                )
            except Exception as e:
                self.logger.error(f"Error in on_direct_message callback: {e}")

    async def on_message(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        msg_type: str,
        msg_content: Union[str, dict],
        username: str,
        client_info: Dict[str, Any],
        session: Dict[str, Any]
    ):
        """Method called when a message is received."""
        pass

    async def _on_message(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        msg_type: str,
        msg_content: Union[str, dict],
        username: str,
        client_info: Dict[str, Any],
        session: Dict[str, Any]
    ):
        """Internal method to handle message events."""
        try:
            await self.on_message(
                ws,
                channel,
                msg_type,
                msg_content,
                username,
                client_info,
                session
            )
        except Exception as e:
            self.logger.error(
                f"Error in on_message method: {e}"
            )
        handled = False
        for callback in self.on_message_callbacks.get(channel, []):
            try:
                result = await asyncio.create_task(
                    callback(ws, channel, msg_type, msg_content, client_info)
                )
                if result is True:
                    handled = True
                    break
            except Exception as e:
                self.logger.error(f"Error in on_message callback: {e}")

        # If no callback handled it, broadcast to channel
        if not handled and msg_type == 'message':
            await self.broadcast(
                channel,
                {
                    'type': 'message',
                    'username': username,
                    'content': msg_content
                }
            )

    async def on_disconnect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        client_info: Dict[str, Any]
    ):
        """Method called when a client disconnects from the channel."""
        pass

    async def _on_disconnect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        username: str,
        client_info: Dict[str, Any]
    ):
        """Internal method to handle client disconnection events."""
        try:
            await self.on_disconnect(ws, channel, client_info)
        except Exception as e:
            self.logger.error(
                f"Error in on_disconnect method: {e}"
            )
        if channel in self.channels and ws in self.channels[channel]:
            self.channels[channel].remove(ws)

        client_info = None
        async with self.clients_lock:
            if ws in self.clients:
                client_info = self.clients[ws]
                username = client_info['username']
                self.usernames.remove(username)
                del self.clients[ws]

        # Execute on_disconnect callbacks
        if client_info:
            for callback in self.on_disconnect_callbacks.get(channel, []):
                try:
                    await asyncio.create_task(
                        callback(ws, channel, client_info)
                    )
                except Exception as e:
                    self.logger.error(f"Error in on_disconnect callback: {e}")

            # Announce user left to channel
            await self.broadcast(
                channel,
                {
                    'type': 'system',
                    'event': 'user_left',
                    'data': {
                        'username': username,
                        'channel': channel
                    }
                }
            )

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handle a WebSocket connection.
        This is the main handler that processes WebSocket connections.
        """
        channel = request.match_info.get("channel", "default")
        self.logger.debug(
            f"WebSocket connection starting for channel: {channel}"
        )

        # Register the channel if it doesn't exist
        if channel not in self.channels:
            self.register_channel(channel)

        # Create WebSocket
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Generate client info
        client_id = str(uuid.uuid4())

        # Get username from session or query params
        try:
            session = await get_session(request)
        except Exception as e:
            self.logger.error(f"Error getting session: {e}")
            try:
                session = await request.config_dict.get(
                    'aiohttp_session', {}
                ).get('get_session', lambda x: None)(request)
            except TypeError:
                self.logger.warning(
                    f"Anonymous Connection: {e}"
                )
                session = None

        # Check User Session:
        if session and 'username' in session:
            username = session['username']
        else:
            username = request.query.get(
                'username', f'User{client_id[:5]}'
            )

        try:
            # Ensure username is unique
            async with self.clients_lock:
                initial_username = username
                suffix = 1
                while username in self.usernames:
                    username = f"{initial_username}_{suffix}"
                    suffix += 1

                # Store client information
                client_info = {
                    'id': client_id,
                    'username': username,
                    'channel': channel,
                    'request': request,
                    'ip': request.remote,
                    'headers': dict(request.headers),
                    'connected_at': asyncio.get_event_loop().time()
                }
                # TODO: log client information

                self.clients[ws] = client_info
                self.usernames.add(username)

            # Add WebSocket to the channel
            self.channels[channel].append(ws)

            # Notify the client of their username
            await ws.send_str(json_encoder({
                'type': 'system',
                'event': 'connected',
                'data': {
                    'username': username,
                    'channel': channel
                }
            }))
            # Execute the on_connection method:
            await self._on_connect(
                ws,
                channel,
                username,
                client_info,
                session
            )

            # Main message processing loop
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    if msg.data == 'close':
                        await ws.close()
                        break
                    try:
                        # Try to parse as JSON first
                        data = json_decoder(msg.data)
                        msg_type = data.get('type', 'message')
                        msg_content = data.get('content', {})
                        target = data.get('target', None)  # For direct messages
                    except orjson.JSONDecodeError:
                        # Fallback to plain text
                        msg_type = 'message'
                        msg_content = msg.data
                        target = None

                    # Handle direct messages
                    if msg_type == 'direct' and target:
                        # Prepare the message
                        direct_msg = {
                            'type': 'direct',
                            'from': username,
                            'content': msg_content
                        }

                        # Send the message to the recipient
                        await self._on_direct(
                            ws,
                            channel,
                            target,
                            direct_msg,
                            sender_info=client_info
                        )

                        continue

                    # Execute on_message callbacks
                    await self._on_message(
                        ws,
                        channel,
                        msg_type,
                        msg_content,
                        username,
                        client_info,
                        session
                    )

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error(
                        f"WebSocket connection closed with exception: {ws.exception()}"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    for callback in self.on_message_callbacks[channel]:
                        await asyncio.create_task(
                            callback(ws, channel, "binary", msg.data)
                        )
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    break

        except Exception as e:
            self.logger.exception(
                f"Error in WebSocket handler: {e}"
            )

        finally:
            # Clean up on disconnect
            await self._on_disconnect(ws, channel, username, client_info)
        return ws
