"""
SSE Integration for Navigator Views and Handlers.

Extends BaseHandler and BaseView with SSE functionality.
"""
from typing import Dict, Any, Optional, Callable
from aiohttp import web
from navconfig.logging import logging
from .manager import SSEManager


class SSEMixin:
    """
    Mixin class that adds SSE functionality to Navigator views.

    Usage in your view:
        class MyView(BaseView, SSEMixin):
            async def post(self):
                # Start a long-running task
                task_id = await self.create_task("report_generation")

                # Start background task
                asyncio.create_task(self._generate_report(task_id))

                return self.json_response({
                    "task_id": task_id,
                    "sse_url": f"/events/{task_id}"
                })

            async def _generate_report(self, task_id: str):
                try:
                    # Simulate progress updates
                    await self.notify_progress(task_id, {"progress": 25, "message": "Processing data..."})
                    await asyncio.sleep(2)

                    await self.notify_progress(task_id, {"progress": 75, "message": "Generating report..."})
                    await asyncio.sleep(3)

                    # Send final result
                    await self.notify_result(task_id, {
                        "status": "success",
                        "download_url": "/downloads/report.pdf"
                    })
                except Exception as e:
                    await self.notify_error(task_id, {"error": str(e)})
    """
    logger = logging.getLogger('navigator.SSEMixin')

    @property
    def sse_manager(self) -> SSEManager:
        """Get the SSE manager from the application."""
        if 'sse_manager' not in self.request.app:
            raise RuntimeError(
                "SSE Manager not configured. Add SSE manager to your app: "
                "app['sse_manager'] = SSEManager()"
            )
        return self.request.app['sse_manager']

    async def create_task(
        self,
        task_type: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new SSE task notification.

        Args:
            task_type: Type of task (e.g., 'report_generation', 'data_export')
            user_id: Optional user identifier (can be extracted from session)
            metadata: Optional metadata for the task

        Returns:
            Task UUID for SSE subscription
        """
        # Try to extract user_id from session if not provided
        if user_id is None:
            user_id = await self._extract_user_id()

        return await self.sse_manager.create_task_notification(
            task_type=task_type,
            user_id=user_id,
            metadata=metadata
        )

    async def notify_progress(
        self,
        task_id: str,
        progress_data: Dict[str, Any]
    ) -> int:
        """
        Send progress update for a task.

        Args:
            task_id: Task identifier
            progress_data: Progress information (e.g., {"progress": 50, "message": "Processing..."})

        Returns:
            Number of clients that received the update
        """
        return await self.sse_manager.broadcast_task_progress(task_id, progress_data)

    async def notify_result(
        self,
        task_id: str,
        result_data: Dict[str, Any],
        close_connections: bool = True
    ) -> int:
        """
        Send final result for a task.

        Args:
            task_id: Task identifier
            result_data: Final result data
            close_connections: Whether to close SSE connections after sending

        Returns:
            Number of clients that received the result
        """
        return await self.sse_manager.broadcast_task_result(
            task_id, result_data, close_connections
        )

    async def notify_error(
        self,
        task_id: str,
        error_data: Dict[str, Any],
        close_connections: bool = True
    ) -> int:
        """
        Send error notification for a task.

        Args:
            task_id: Task identifier
            error_data: Error information
            close_connections: Whether to close SSE connections after sending

        Returns:
            Number of clients that received the error
        """
        return await self.sse_manager.broadcast_task_error(
            task_id, error_data, close_connections
        )

    async def _extract_user_id(self) -> Optional[str]:
        """
        Extract user ID from session or request.
        Override this method to customize user identification.
        """
        try:
            # Try to get user from Navigator session
            if hasattr(self, 'session'):
                session = await self.session()
                if session and 'user_id' in session:
                    return str(session['user_id'])

            # Try to get from Authorization header
            auth_header = self.request.headers.get('Authorization')
            if auth_header:
                # You can implement JWT/token parsing here
                pass

            # Try to get from request params
            if user_id := self.request.query.get('user_id'):
                return user_id

        except Exception as e:
            self.logger.warning(
                f"Could not extract user_id: {e}"
            )

        return None


class SSEEventView(SSEMixin):
    """
    Dedicated view for handling SSE connections.

    Usage:
        # In your routes
        app.router.add_get('/events/{task_id}', SSEEventView)
    """

    async def get(self) -> web.StreamResponse:
        """Handle SSE connection requests."""
        task_id = self.request.match_info.get('task_id')
        if not task_id:
            raise web.HTTPBadRequest(text="task_id is required")

        user_id = await self._extract_user_id()

        return await self.sse_manager.subscribe_to_task(
            self.request, task_id, user_id
        )


def create_sse_routes(sse_manager: SSEManager) -> list:
    """
    Create standard SSE routes for Navigator.

    Args:
        sse_manager: SSE manager instance

    Returns:
        List of route configurations for Navigator
    """
    from navigator.routes import path

    class SSEView:
        def __init__(self):
            self.sse_manager = sse_manager

        async def handle_sse(self, request: web.Request) -> web.StreamResponse:
            task_id = request.match_info.get('task_id')
            if not task_id:
                raise web.HTTPBadRequest(text="task_id is required")

            # Extract user_id from query params or headers
            user_id = request.query.get('user_id')
            if not user_id:
                auth_header = request.headers.get('Authorization')
                # Implement your auth extraction logic here

            return await self.sse_manager.subscribe_to_task(request, task_id, user_id)

        async def sse_stats(self, request: web.Request) -> web.Response:
            """Get SSE statistics endpoint."""
            stats = self.sse_manager.get_stats()
            return web.json_response(stats)

    sse_view = SSEView()

    return [
        path("GET", "/events/{task_id}", sse_view.handle_sse, name="sse_events"),
        path("GET", "/sse/stats", sse_view.sse_stats, name="sse_stats"),
    ]


async def setup_sse_manager(app: web.Application) -> SSEManager:
    """
    Setup SSE manager for a Navigator application.

    Usage:
        # In your app startup
        async def setup_app():
            app = web.Application()
            sse_manager = await setup_sse_manager(app)
            return app
    """
    sse_manager = SSEManager()
    app['sse_manager'] = sse_manager

    # Start the cleanup task
    await sse_manager.start_cleanup_task()

    # Setup cleanup on app shutdown
    async def cleanup_sse(app):
        await sse_manager.stop()

    app.on_cleanup.append(cleanup_sse)
    return sse_manager


# Decorator for easy task creation
def sse_task(task_type: str, user_id_param: Optional[str] = None):
    """
    Decorator to automatically create SSE tasks for long-running operations.

    Usage:
        class MyView(BaseView, SSEMixin):
            @sse_task("report_generation")
            async def generate_report(self):
                # This method will automatically get a task_id parameter
                # and can use self.notify_progress(), self.notify_result()
                pass
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(self, *args, **kwargs):
            # Extract user_id if specified
            user_id = None
            if user_id_param and hasattr(self.request, user_id_param):
                user_id = getattr(self.request, user_id_param)
            elif user_id_param and user_id_param in self.request.query:
                user_id = self.request.query[user_id_param]
            else:
                user_id = await self._extract_user_id()

            # Create task
            task_id = await self.create_task(task_type, user_id)

            # Add task_id to kwargs
            kwargs['task_id'] = task_id

            try:
                result = await func(self, *args, **kwargs)
                return result
            except Exception as e:
                # Auto-notify error
                await self.notify_error(task_id, {"error": str(e)})
                raise

        return wrapper
    return decorator
