"""
FileServingExtension.

Decoupled aiohttp web-serving layer for any FileManagerInterface.
Handles route registration, HTTP streaming, Range requests (HTTP 206),
caching headers, and path sanitization.

Extends BaseExtension for proper aiohttp integration.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Optional

from aiohttp import web

from ...applications.base import BaseApplication
from ...extensions import BaseExtension
from ...types import WebApp
from .abstract import FileManagerInterface


class FileServingExtension(BaseExtension):
    """Aiohttp extension that serves files from any FileManagerInterface.

    Registers a GET route ``{route}/{filepath:.*}`` and streams files
    from the configured manager.  Supports:

    - Range requests (HTTP 206 Partial Content)
    - Caching headers (7-day Expires, Cache-Control: private)
    - Content-Disposition for downloads
    - Path sanitization via PurePath to prevent traversal
    - 404 for missing files

    Attributes:
        name: Extension key stored in app context (default ``"fileserving"``).
    """

    name: str = "fileserving"

    CHUNK_SIZE: int = 1024 * 1024  # 1MB streaming chunks

    def __init__(
        self,
        manager: FileManagerInterface,
        route: str = "/data",
        manager_name: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize FileServingExtension.

        Args:
            manager: Any FileManagerInterface implementation.
            route: URL prefix for serving files (default ``"/data"``).
            manager_name: If provided, overrides the ``name`` attribute so
                          multiple extensions can coexist in the same app
                          (e.g. ``"gcsfile"``, ``"s3file"``).
            **kwargs: Passed through to BaseExtension.
        """
        super().__init__(**kwargs)
        self.manager = manager
        self.route = route.rstrip("/")
        if manager_name:
            self.name = manager_name
        # Use manager_name from the manager class if available
        elif hasattr(manager, "manager_name") and manager.manager_name:
            self.name = manager.manager_name

    # ------------------------------------------------------------------ #
    # BaseExtension integration                                            #
    # ------------------------------------------------------------------ #

    def setup(self, app: WebApp) -> WebApp:
        """Register the extension and its route with the aiohttp app.

        Args:
            app: An aiohttp WebApp or BaseApplication instance.

        Returns:
            The configured app.
        """
        # Resolve BaseApplication → raw aiohttp.Application
        if isinstance(app, BaseApplication):
            raw_app = app.get_app()
        else:
            raw_app = app

        self.app = raw_app

        # Store extension in app context under self.name
        raw_app[self.name] = self
        try:
            raw_app.extensions[self.name] = self
        except AttributeError:
            raw_app.extensions = {}
            raw_app.extensions[self.name] = self

        # Register the file-serving route
        route_pattern = self.route + "/{filepath:.*}"
        raw_app.router.add_get(route_pattern, self.handle_file)

        self.logger.info(
            "FileServingExtension '%s' registered route: GET %s",
            self.name,
            route_pattern,
        )
        return raw_app

    # ------------------------------------------------------------------ #
    # Request handler                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_range_header(range_header: str, file_size: int):
        """Parse a Range header into (start, end) byte offsets.

        Args:
            range_header: Value of the HTTP Range header (e.g. ``"bytes=0-1023"``).
            file_size: Total file size in bytes.

        Returns:
            Tuple (start, end) where both values are inclusive byte offsets.

        Raises:
            web.HTTPBadRequest: If the header is malformed.
            web.HTTPRequestRangeNotSatisfiable: If the range is out of bounds.
        """
        try:
            unit, ranges = range_header.strip().split("=", 1)
            if unit.strip() != "bytes":
                raise web.HTTPBadRequest(reason="Only byte ranges are supported.")
            start_str, end_str = ranges.split("-", 1)
            start = int(start_str) if start_str.strip() else 0
            end = int(end_str) if end_str.strip() else file_size - 1
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest(reason=f"Invalid Range header: {range_header!r}")

        if start < 0 or end < start or end >= file_size:
            raise web.HTTPRequestRangeNotSatisfiable(
                headers={"Content-Range": f"bytes */{file_size}"}
            )
        return start, end

    async def handle_file(self, request: web.Request) -> web.StreamResponse:
        """Stream a file from the manager to the HTTP client.

        Supports full file streaming and Range requests (HTTP 206).

        Args:
            request: Incoming aiohttp request.

        Returns:
            StreamResponse with file content.

        Raises:
            web.HTTPNotFound: If no filepath is provided.
        """
        raw_path = request.match_info.get("filepath", "")
        if not raw_path:
            raise web.HTTPNotFound()

        # Sanitize path to prevent traversal
        try:
            safe_path = str(PurePath(raw_path).relative_to("/"))
        except ValueError:
            safe_path = raw_path.lstrip("/")

        # Reject obvious traversal attempts
        if ".." in safe_path:
            return web.Response(status=403, text="Forbidden")

        # Check if file exists via manager
        file_exists = await self.manager.exists(safe_path)
        if not file_exists:
            return web.Response(status=404, text="File not found")

        # Retrieve metadata for content-length / content-type
        try:
            meta = await self.manager.get_file_metadata(safe_path)
        except (FileNotFoundError, Exception):
            return web.Response(status=404, text="File not found")

        # Build caching headers
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=7)
        last_modified = now - timedelta(hours=1)
        filename = os.path.basename(safe_path)

        base_headers = {
            "Pragma": "public",
            "Last-Modified": last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Expires": expires.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Cache-Control": "private",
            "Content-Description": "File Transfer",
            "Content-Transfer-Encoding": "binary",
            "Date": now.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": meta.content_type or "application/octet-stream",
        }

        file_size = meta.size

        # ── Range request ──────────────────────────────────────────────
        if "Range" in request.headers and file_size:
            start, end = self._parse_range_header(
                request.headers["Range"], file_size
            )
            content_length = end - start + 1
            response = web.StreamResponse(
                status=206,
                reason="Partial Content",
                headers={
                    **base_headers,
                    "Content-Length": str(content_length),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                },
            )
            await response.prepare(request)

            # Download the whole file into a buffer and stream the slice
            # (managers don't expose a seek interface yet)
            import io

            buf = io.BytesIO()
            await self.manager.download_file(safe_path, buf)
            buf.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = buf.read(min(self.CHUNK_SIZE, remaining))
                if not chunk:
                    break
                await response.write(chunk)
                remaining -= len(chunk)

            await response.write_eof()
            return response

        # ── Full file ─────────────────────────────────────────────────
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                **base_headers,
                "Content-Length": str(file_size) if file_size else "",
                "Accept-Ranges": "bytes",
            },
        )
        await response.prepare(request)

        import io

        buf = io.BytesIO()
        await self.manager.download_file(safe_path, buf)
        buf.seek(0)
        while True:
            chunk = buf.read(self.CHUNK_SIZE)
            if not chunk:
                break
            await response.write(chunk)

        await response.write_eof()
        return response
