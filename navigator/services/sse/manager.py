"""
Navigator SSE (Server-Sent Events) Manager.

Provides task-based SSE notifications integrated with Navigator's BaseHandler.
"""
from typing import Dict, List, Optional, Any
import asyncio
import uuid
import contextlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from aiohttp import web
from aiohttp_sse import sse_response
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging


@dataclass
class SSEConnection:
    """Represents an active SSE connection."""
    task_id: str
    response: Any  # sse_response object
    request: web.Request
    created_at: datetime = field(default_factory=datetime.now)
    last_ping: datetime = field(default_factory=datetime.now)
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # Unique connection ID

    @property
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Check if connection has expired."""
        return datetime.now() - self.last_ping > timedelta(minutes=timeout_minutes)


class SSEManager:
    """
    Manages Server-Sent Events connections and task notifications.

    Note: Uses lists instead of sets for connections since SSEConnection objects
    are not hashable (contain mutable response/request objects).

    Usage:
        # In your Navigator app startup
        sse_manager = SSEManager()
        app['sse_manager'] = sse_manager

        # In a view that starts a long task
        task_id = await self.create_task_notification("report_generation")
        # Start your background task here
        return {"task_id": task_id, "sse_url": f"/events/{task_id}"}

        # When task completes
        await self.broadcast_task_result(task_id, {"status": "completed", "result": data})
    """
    def __init__(self):
        self._connections: Dict[str, List[SSEConnection]] = {}
        self._pending_tasks: Dict[str, Dict[str, Any]] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger('navigator.sse')
        self._running = True

    async def start_cleanup_task(self):
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_expired_connections())

    async def stop(self):
        """Stop the SSE manager and cleanup."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        # Close all active connections
        for connections in self._connections.values():
            for conn in connections.copy():
                await self._close_connection(conn)

    async def create_task_notification(
        self,
        task_type: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new task notification identifier.

        Args:
            task_type: Type of task (e.g., 'report_generation', 'data_export')
            user_id: Optional user identifier for filtering
            metadata: Optional metadata to associate with the task

        Returns:
            UUID string to be used for SSE subscription
        """
        task_id = str(uuid.uuid4())
        self._pending_tasks[task_id] = {
            'task_type': task_type,
            'user_id': user_id,
            'created_at': datetime.now(),
            'metadata': metadata or {},
            'status': 'pending'
        }

        self.logger.info(f"Created task notification: {task_id} ({task_type})")
        return task_id

    async def subscribe_to_task(
        self,
        request: web.Request,
        task_id: str,
        user_id: Optional[str] = None
    ) -> web.StreamResponse:
        """
        Subscribe to SSE events for a specific task.

        This method should be called from a view that handles SSE connections.
        """
        if task_id not in self._pending_tasks:
            raise web.HTTPNotFound(text=f"Task {task_id} not found")

        task_info = self._pending_tasks[task_id]

        # Check user authorization if needed
        if task_info.get('user_id') and user_id != task_info.get('user_id'):
            raise web.HTTPForbidden(text="Access denied to this task")

        async with sse_response(request) as resp:
            # Create connection object
            connection = SSEConnection(
                task_id=task_id,
                response=resp,
                request=request,
                user_id=user_id,
                metadata=task_info.get('metadata', {})
            )

            # Register the connection
            if task_id not in self._connections:
                self._connections[task_id] = []
            self._connections[task_id].append(connection)

            self.logger.info(f"SSE connection established for task: {task_id}")

            # Send initial connection confirmation
            await self._send_to_connection(connection, {
                'type': 'connection',
                'status': 'connected',
                'task_id': task_id,
                'task_type': task_info['task_type'],
                'timestamp': datetime.now().isoformat()
            })

            try:
                # Keep connection alive with periodic pings
                while resp.is_connected():
                    await asyncio.sleep(30)  # Ping every 30 seconds
                    connection.last_ping = datetime.now()

                    await self._send_to_connection(connection, {
                        'type': 'ping',
                        'timestamp': datetime.now().isoformat()
                    })

            except asyncio.CancelledError:
                pass
            finally:
                # Clean up connection
                await self._close_connection(connection)

        return resp

    async def broadcast_task_progress(
        self,
        task_id: str,
        progress_data: Dict[str, Any]
    ) -> int:
        """
        Broadcast progress update for a task.

        Args:
            task_id: Task identifier
            progress_data: Progress information to send

        Returns:
            Number of connections that received the message
        """
        if task_id not in self._connections:
            self.logger.warning(f"No connections found for task: {task_id}")
            return 0

        message = {
            'type': 'progress',
            'task_id': task_id,
            'timestamp': datetime.now().isoformat(),
            **progress_data
        }

        return await self._broadcast_to_task(task_id, message)

    async def broadcast_task_result(
        self,
        task_id: str,
        result_data: Dict[str, Any],
        close_connections: bool = True
    ) -> int:
        """
        Broadcast final result for a task.

        Args:
            task_id: Task identifier
            result_data: Final result data
            close_connections: Whether to close connections after sending

        Returns:
            Number of connections that received the message
        """
        if task_id not in self._connections:
            self.logger.warning(f"No connections found for task: {task_id}")
            return 0

        message = {
            'type': 'result',
            'task_id': task_id,
            'timestamp': datetime.now().isoformat(),
            **result_data
        }

        sent_count = await self._broadcast_to_task(task_id, message)

        # Mark task as completed
        if task_id in self._pending_tasks:
            self._pending_tasks[task_id]['status'] = 'completed'
            self._pending_tasks[task_id]['completed_at'] = datetime.now()

        # Optionally close all connections for this task
        if close_connections:
            await self._close_task_connections(task_id)

        return sent_count

    async def broadcast_task_error(
        self,
        task_id: str,
        error_data: Dict[str, Any],
        close_connections: bool = True
    ) -> int:
        """
        Broadcast error for a task.

        Args:
            task_id: Task identifier
            error_data: Error information
            close_connections: Whether to close connections after sending

        Returns:
            Number of connections that received the message
        """
        message = {
            'type': 'error',
            'task_id': task_id,
            'timestamp': datetime.now().isoformat(),
            **error_data
        }

        sent_count = await self._broadcast_to_task(task_id, message)

        # Mark task as failed
        if task_id in self._pending_tasks:
            self._pending_tasks[task_id]['status'] = 'failed'
            self._pending_tasks[task_id]['completed_at'] = datetime.now()

        if close_connections:
            await self._close_task_connections(task_id)

        return sent_count

    # Private methods

    async def _broadcast_to_task(self, task_id: str, message: Dict[str, Any]) -> int:
        """Broadcast message to all connections for a task."""
        if task_id not in self._connections:
            return 0

        connections = self._connections[task_id].copy()
        sent_count = 0

        for connection in connections:
            if await self._send_to_connection(connection, message):
                sent_count += 1

        return sent_count

    async def _send_to_connection(
        self,
        connection: SSEConnection,
        message: Dict[str, Any]
    ) -> bool:
        """Send message to a specific connection."""
        try:
            if not connection.response.is_connected():
                await self._close_connection(connection)
                return False

            data = json_encoder(message)
            await connection.response.send(data)
            return True

        except Exception as e:
            self.logger.error(f"Error sending SSE message: {e}")
            await self._close_connection(connection)
            return False

    async def _close_connection(self, connection: SSEConnection):
        """Close and cleanup a connection."""
        try:
            if connection.task_id in self._connections:
                self._connections[connection.task_id].remove(connection)

                # Remove task connections set if empty
                if not self._connections[connection.task_id]:
                    del self._connections[connection.task_id]

        except Exception as e:
            self.logger.error(f"Error closing SSE connection: {e}")

    async def _close_task_connections(self, task_id: str):
        """Close all connections for a specific task."""
        if task_id in self._connections:
            connections = self._connections[task_id].copy()
            for connection in connections:
                await self._close_connection(connection)

    async def _cleanup_expired_connections(self):
        """Background task to cleanup expired connections and tasks."""
        while self._running:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                now = datetime.now()
                expired_connections = []

                # Find expired connections
                for task_id, connections in self._connections.items():
                    expired_connections.extend(
                        connection
                        for connection in connections.copy()
                        if connection.is_expired
                    )

                # Close expired connections
                for connection in expired_connections:
                    await self._close_connection(connection)

                # Cleanup old completed tasks (older than 1 hour)
                expired_tasks = [
                    task_id for task_id, task_info in self._pending_tasks.items()
                    if task_info.get('completed_at') and now - task_info['completed_at'] > timedelta(hours=1)
                ]

                for task_id in expired_tasks:
                    del self._pending_tasks[task_id]

                if expired_connections or expired_tasks:
                    self.logger.info(
                        f"Cleaned up {len(expired_connections)} connections "
                        f"and {len(expired_tasks)} tasks"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in SSE cleanup task: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get SSE manager statistics."""
        total_connections = sum(len(conns) for conns in self._connections.values())

        return {
            'total_tasks': len(self._pending_tasks),
            'active_connections': total_connections,
            'active_task_connections': len(self._connections),
            'pending_tasks': len([
                t for t in self._pending_tasks.values()
                if t['status'] == 'pending'
            ]),
            'completed_tasks': len([
                t for t in self._pending_tasks.values()
                if t['status'] in ['completed', 'failed']
            ])
        }
