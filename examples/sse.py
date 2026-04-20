"""
Complete example of SSE integration with Navigator.

This shows how to:
1. Setup SSE in your Navigator app
2. Create views that use SSE for long-running tasks
3. Handle the frontend SSE connections
"""

import asyncio
from datetime import datetime
from aiohttp import web
from navigator import Application
from navigator.views import BaseView
from navigator.routes import path
# Import our SSE components
from navigator.services.sse import (
    SSEMixin,
    setup_sse_manager,
    create_sse_routes,
    sse_task
)


# Example: Report Generation View with SSE
class ReportView(BaseView, SSEMixin):
    """
    Example view that generates reports with real-time progress updates.
    """

    async def post(self):
        """Start a report generation task."""
        request_data = await self.get_json()
        report_type = request_data.get('report_type', 'basic')

        # Create SSE task
        task_id = await self.create_task(
            task_type="report_generation",
            metadata={"report_type": report_type}
        )

        # Start background task
        asyncio.create_task(self._generate_report_async(task_id, report_type))

        # Return task info to client
        return self.json_response({
            "success": True,
            "task_id": task_id,
            "sse_url": f"/events/{task_id}",
            "estimated_time": "2-5 minutes"
        })

    async def _generate_report_async(self, task_id: str, report_type: str):
        """Background task that generates the report with progress updates."""
        try:
            # Step 1: Data collection
            await self.notify_progress(task_id, {
                "progress": 10,
                "message": "Starting data collection...",
                "step": "data_collection"
            })
            await asyncio.sleep(2)  # Simulate work

            # Step 2: Data processing
            await self.notify_progress(task_id, {
                "progress": 40,
                "message": "Processing collected data...",
                "step": "processing"
            })
            await asyncio.sleep(3)  # Simulate work

            # Step 3: Report generation
            await self.notify_progress(task_id, {
                "progress": 70,
                "message": "Generating report document...",
                "step": "generation"
            })
            await asyncio.sleep(2)  # Simulate work

            # Step 4: Finalization
            await self.notify_progress(task_id, {
                "progress": 90,
                "message": "Finalizing report...",
                "step": "finalization"
            })
            await asyncio.sleep(1)  # Simulate work

            # Complete the task
            report_url = f"/downloads/report_{task_id}.pdf"
            await self.notify_result(task_id, {
                "status": "completed",
                "progress": 100,
                "message": "Report generated successfully!",
                "download_url": report_url,
                "metadata": {
                    "report_type": report_type,
                    "generated_at": datetime.now().isoformat(),
                    "file_size": "2.3 MB"
                }
            })

        except Exception as e:
            await self.notify_error(task_id, {
                "status": "failed",
                "error": str(e),
                "message": "Report generation failed"
            })


# Example: Data Export View with SSE using decorator
class DataExportView(BaseView, SSEMixin):
    """
    Example view using the @sse_task decorator for cleaner code.
    """

    @sse_task("data_export")
    async def post(self, task_id: str):  # task_id is automatically injected
        """Export data with automatic SSE task creation."""
        request_data = await self.json()
        format_type = request_data.get('format', 'csv')

        try:
            # Export process with progress updates
            await self.notify_progress(task_id, {
                "progress": 20,
                "message": "Querying database..."
            })
            # Simulate database query
            await asyncio.sleep(1)

            await self.notify_progress(task_id, {
                "progress": 60,
                "message": f"Converting to {format_type.upper()}..."
            })
            # Simulate format conversion
            await asyncio.sleep(2)

            # Complete
            export_url = f"/downloads/export_{task_id}.{format_type}"
            await self.notify_result(task_id, {
                "status": "completed",
                "download_url": export_url,
                "format": format_type
            })

            return self.json_response({
                "success": True,
                "task_id": task_id,
                "sse_url": f"/events/{task_id}"
            })

        except Exception as e:
            # Error is automatically notified by the decorator
            raise


# Example: SSE Statistics View
class SSEStatsView(BaseView, SSEMixin):
    """View to get SSE manager statistics."""

    async def get(self):
        """Get current SSE statistics."""
        stats = self.sse_manager.get_stats()
        return self.json_response(stats)


# Navigator Application Setup
class SSEApplication(Application):
    """
    Navigator application with SSE support.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sse_manager = None

    async def setup_sse(self):
        """Setup SSE manager and routes."""
        app = self.get_app()

        # Setup SSE manager
        self.sse_manager = await setup_sse_manager(app)

        # Add SSE routes
        sse_routes = create_sse_routes(self.sse_manager)

        # Add our custom routes
        custom_routes = [
            path("POST", "/api/reports/generate", ReportView, name="my_generate_report"),
            path("POST", "/api/data/export", DataExportView, name="my_export_data"),
            path("GET", "/api/sse/stats", SSEStatsView, name="my_sse_stats"),

            # Serve a demo HTML page
            path("GET", "/serve", self.serve_demo_page, name="demo"),
        ]

        # Add all routes
        all_routes = sse_routes + custom_routes
        self.add_routes(all_routes)

        return self.sse_manager

    async def serve_demo_page(self, request):
        """Serve a demo HTML page for testing SSE."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Navigator SSE Demo</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .container { max-width: 800px; margin: 0 auto; }
                .progress { width: 100%; height: 20px; background: #f0f0f0; border-radius: 10px; overflow: hidden; }
                .progress-bar { height: 100%; background: #4CAF50; transition: width 0.3s; }
                .log { height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; background: #f9f9f9; }
                button { padding: 10px 20px; margin: 10px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
                button:hover { background: #0056b3; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Navigator SSE Demo</h1>

                <div>
                    <button onclick="startReport()">Generate Report</button>
                    <button onclick="startExport()">Export Data</button>
                    <button onclick="getStats()">Get Stats</button>
                </div>

                <div id="task-info" style="margin: 20px 0;"></div>

                <div>
                    <h3>Progress:</h3>
                    <div class="progress">
                        <div id="progress-bar" class="progress-bar" style="width: 0%"></div>
                    </div>
                    <div id="progress-text">Ready to start...</div>
                </div>

                <div>
                    <h3>Event Log:</h3>
                    <div id="log" class="log"></div>
                </div>
            </div>

            <script>
                let currentEventSource = null;

                function log(message) {
                    const logDiv = document.getElementById('log');
                    const time = new Date().toLocaleTimeString();
                    logDiv.innerHTML += `[${time}] ${message}\\n`;
                    logDiv.scrollTop = logDiv.scrollHeight;
                }

                function updateProgress(progress, message) {
                    document.getElementById('progress-bar').style.width = progress + '%';
                    document.getElementById('progress-text').textContent = message || `${progress}%`;
                }

                function connectToSSE(taskId) {
                    if (currentEventSource) {
                        currentEventSource.close();
                    }

                    const url = `/events/${taskId}`;
                    log(`Connecting to SSE: ${url}`);

                    currentEventSource = new EventSource(url);

                    currentEventSource.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        log(`Received: ${JSON.stringify(data)}`);

                        if (data.type === 'progress') {
                            updateProgress(data.progress || 0, data.message);
                        } else if (data.type === 'result') {
                            updateProgress(100, 'Completed!');
                            if (data.download_url) {
                                log(`Download ready: ${data.download_url}`);
                            }
                            currentEventSource.close();
                        } else if (data.type === 'error') {
                            updateProgress(0, `Error: ${data.error}`);
                            currentEventSource.close();
                        }
                    };

                    currentEventSource.onerror = function(event) {
                        log('SSE connection error');
                        currentEventSource.close();
                    };
                }

                async function startReport() {
                    try {
                        const response = await fetch('/api/reports/generate', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({report_type: 'detailed'})
                        });

                        const data = await response.json();

                        if (data.success) {
                            document.getElementById('task-info').innerHTML =
                                `Task ID: ${data.task_id}<br>SSE URL: ${data.sse_url}`;

                            log(`Started report generation: ${data.task_id}`);
                            connectToSSE(data.task_id);
                        } else {
                            log('Failed to start report generation');
                        }
                    } catch (error) {
                        log(`Error: ${error.message}`);
                    }
                }

                async function startExport() {
                    try {
                        const response = await fetch('/api/data/export', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({format: 'csv'})
                        });

                        const data = await response.json();

                        if (data.success) {
                            document.getElementById('task-info').innerHTML =
                                `Task ID: ${data.task_id}<br>SSE URL: ${data.sse_url}`;

                            log(`Started data export: ${data.task_id}`);
                            connectToSSE(data.task_id);
                        } else {
                            log('Failed to start data export');
                        }
                    } catch (error) {
                        log(`Error: ${error.message}`);
                    }
                }

                async function getStats() {
                    try {
                        const response = await fetch('/api/sse/stats');
                        const stats = await response.json();
                        log(`SSE Stats: ${JSON.stringify(stats, null, 2)}`);
                    } catch (error) {
                        log(`Error getting stats: ${error.message}`);
                    }
                }
            </script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')


# Example startup script
async def create_app():
    """Create and configure the Navigator app with SSE."""
    app = SSEApplication()

    # Setup SSE
    await app.setup_sse()
    return app.get_app()


if __name__ == '__main__':
    """
    Run the example:

    python sse_example.py

    Then visit:
    - http://localhost:5000/ for the demo page
    - POST http://localhost:5000/api/reports/generate to start a report
    - GET http://localhost:5000/events/{task_id} to connect to SSE
    """
    app = create_app()
    web.run_app(app, host='localhost', port=5000)
