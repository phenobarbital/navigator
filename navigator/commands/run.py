"""
Navigator Run Command.
Starts Navigator applications similar to 'python run.py'.
"""
import os
import sys
import asyncio
import subprocess
from pathlib import Path
from navconfig.logging import logging
from navconfig import config
from . import BaseCommand


logging.getLogger('watchdog').setLevel(logging.WARNING)
logger = logging.getLogger("navigator.command")


class RunCommand(BaseCommand):
    """Start Navigator application server."""

    help = "Start the Navigator application server."
    _version: str = "1.0.1"
    default_action: str = "start"  # Default action for 'nav run'

    def parse_arguments(self, parser):
        """Add custom arguments for the run command."""
        parser.add_argument(
            "--host",
            type=str,
            help="Host address to bind to (overrides config)"
        )
        parser.add_argument(
            "--port",
            type=int,
            help="Port to bind to (overrides config)"
        )
        parser.add_argument(
            "--ssl",
            action="store_true",
            help="Enable SSL (overrides config)"
        )
        parser.add_argument(
            "--no-ssl",
            action="store_true",
            help="Disable SSL (overrides config)"
        )
        parser.add_argument(
            "--reload",
            action="store_true",
            help="Enable auto-reload on file changes"
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=1,
            help="Number of worker processes (for production)"
        )
        parser.add_argument(
            "--access-log",
            action="store_true",
            help="Enable access logging"
        )
        parser.add_argument(
            "--no-access-log",
            action="store_true",
            help="Disable access logging"
        )

    def start(self, options, **kwargs):
        """Start the Navigator application server."""
        path = Path(kwargs["project_path"]).resolve()

        output = "Navigator application started successfully."

        if options.debug:
            self.write(":: Starting Navigator Application Server", level="INFO")

        try:
            # Check if run.py exists
            run_file = path.joinpath("run.py")
            if not run_file.exists():
                self.write(":: No run.py file found", level="WARN")
                self.write(":: You can create one with 'nav init' or create it manually", level="INFO")
                output = "Failed: No run.py file found in project root."
                return output

            # Set environment variables based on command options
            env_vars = os.environ.copy()

            if options.host:
                env_vars["APP_HOST"] = options.host
                self.write(f"* Overriding host: {options.host}")

            if options.port:
                env_vars["APP_PORT"] = str(options.port)
                self.write(f"* Overriding port: {options.port}")

            if options.ssl:
                env_vars["SSL"] = "true"
                self.write("* Enabling SSL")

            if options.no_ssl:
                env_vars["SSL"] = "false"
                self.write("* Disabling SSL")

            if options.access_log:
                env_vars["ENABLE_ACCESS_LOG"] = "true"
                self.write("* Enabling access log")

            if options.no_access_log:
                env_vars["ENABLE_ACCESS_LOG"] = "false"
                self.write("* Disabling access log")

            if options.debug:
                env_vars["DEBUG"] = "true"
                self.write("* Debug mode enabled")

            # Prepare the command
            cmd = [sys.executable, "-u", str(run_file)]

            # Show configuration info in debug mode
            if options.debug:
                host = options.host or env_vars.get('APP_HOST', 'localhost')
                port = options.port or env_vars.get('APP_PORT', '5000')
                self.write(f"  - Running: {' '.join(cmd)}")
                self.write(f"  - Host: {host}")
                self.write(f"  - Port: {port}")
                self.write(f"  - Working Directory: {path}")

            if options.reload:
                # Use file watcher for development
                self.write("* Auto-reload enabled (development mode)")
                self._run_with_reload(cmd, path, env_vars)

            elif options.workers > 1:
                # Use gunicorn for production with multiple workers
                self.write(
                    f"* Starting with {options.workers} workers (production mode)"
                )

                # Check if gunicorn is available
                try:
                    subprocess.run(
                        ["gunicorn", "--version"],
                        capture_output=True, check=True
                    )
                except (subprocess.CalledProcessError, FileNotFoundError):
                    self.write(
                        ":: Gunicorn not found. Install with: pip install gunicorn", level="ERROR"
                    )
                    output = "Failed: Gunicorn not found."
                    return output

                host = options.host or env_vars.get('APP_HOST', 'localhost')
                port = options.port or env_vars.get('APP_PORT', '5000')

                gunicorn_cmd = [
                    "gunicorn",
                    "nav:navigator",
                    f"--workers={options.workers}",
                    f"--bind={host}:{port}",
                    "--worker-class=aiohttp.GunicornWebWorker"
                ]

                if path.joinpath("gunicorn_config.py").exists():
                    gunicorn_cmd.extend(["-c", "gunicorn_config.py"])
                    self.write("* Using gunicorn_config.py")

                if options.debug:
                    self.write(f"* Gunicorn command: {' '.join(gunicorn_cmd)}")

                subprocess.run(gunicorn_cmd, cwd=path, env=env_vars)

            else:
                # Single process mode
                self.write("* Starting in single process mode")

                # Execute run.py directly
                if options.debug:
                    self.write("* Executing run.py...")

                result = subprocess.run(cmd, cwd=path, env=env_vars)

                if result.returncode != 0:
                    output = f"Application exited with code {result.returncode}"

        except KeyboardInterrupt:
            self.write("* Server stopped by user", level="WARN")
            output = "Server stopped."

        except Exception as err:
            self.write(f":: Error starting server: {err!s}", level="ERROR")
            if options.debug:
                import traceback
                self.write(traceback.format_exc(), level="DEBUG")
            output = "Failed to start server."

        return output

    def _run_with_reload(self, cmd, path, env_vars):
        """Run the application with file watching for auto-reload."""
        try:
            import time
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            self.write(":: Warning: watchdog not installed. Install with: pip install watchdog", level="WARN")
            self.write(":: Running without reload functionality", level="INFO")
            # Fall back to regular execution
            subprocess.run(cmd, cwd=path, env=env_vars)
            return

        class ReloadHandler(FileSystemEventHandler):
            def __init__(self, restart_func, write_func):
                self.restart_func = restart_func
                self.write_func = write_func

            def on_modified(self, event):
                if event.src_path.endswith(('.py', '.ini', '.env')):
                    self.write_func(f"* File changed: {event.src_path}", level="DEBUG")
                    self.restart_func()

        process = None

        def start_process():
            nonlocal process
            if process:
                self.write("* Stopping previous process...", level="DEBUG")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            self.write("* Starting Navigator application...", level="INFO")
            process = subprocess.Popen(cmd, cwd=path, env=env_vars)

        def restart_process():
            self.write("* Restarting due to file changes...", level="INFO")
            start_process()

        # Start initial process
        start_process()

        # Setup file watcher
        event_handler = ReloadHandler(restart_process, self.write)
        observer = Observer()
        observer.schedule(event_handler, str(path), recursive=True)
        observer.start()

        self.write("* Auto-reload enabled. Press Ctrl+C to stop.", level="INFO")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.write("* Stopping auto-reload...", level="INFO")
            observer.stop()
            if process:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        observer.join()

    def run(self, options, **kwargs):
        """Default run method - alias for start."""
        return self.start(options, **kwargs)

    def stop(self, options, **kwargs):
        """Stop running Navigator processes."""
        self.write(":: Stopping Navigator processes", level="INFO")

        try:
            import psutil
        except ImportError:
            self.write(":: Warning: psutil not installed. Install with: pip install psutil", level="WARN")
            self.write(":: Cannot automatically stop processes", level="INFO")
            return "Failed: psutil not available for process management."

        stopped_count = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any('run.py' in arg or 'navigator' in arg for arg in cmdline):
                    proc.terminate()
                    stopped_count += 1
                    self.write(f"  - Stopped process {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if stopped_count > 0:
            output = f"Stopped {stopped_count} Navigator process(es)."
        else:
            output = "No Navigator processes found running."

        return output

    def status(self, options, **kwargs):
        """Show status of Navigator processes."""
        try:
            import psutil
        except ImportError:
            self.write(":: Warning: psutil not installed. Install with: pip install psutil", level="WARN")
            self.write(":: Cannot check process status", level="INFO")
            return "Failed: psutil not available for process management."

        self.write(":: Navigator Process Status", level="INFO")

        running_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'status']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any('run.py' in arg or 'navigator' in arg for arg in cmdline):
                    running_processes.append({
                        'pid': proc.info['pid'],
                        'status': proc.info['status'],
                        'cmdline': ' '.join(cmdline)
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if running_processes:
            for proc in running_processes:
                self.write(f"  - PID {proc['pid']}: {proc['status']} - {proc['cmdline']}")
            output = f"Found {len(running_processes)} running Navigator process(es)."
        else:
            self.write("  - No Navigator processes running")
            output = "No Navigator processes found running."

        return output

    def configure(self):
        """Configure the command (override to avoid template parser setup)."""
        # We don't need the template parser for the run command
        pass
