"""
TempFile Manager.

Exposing Temp Files created as static File Manager.
"""
from typing import Union
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, urljoin
from aiohttp import web
from ..types import WebApp
from ..applications.base import BaseApplication


class TempFileManager:
    """
    TempFileManager class.

    Exposing Temp Files created as static File Manager.
    """
    def __init__(self):
        self.app = None
        self.route = '/data'
        self.base_url = None

    @staticmethod
    def create_temp_file(suffix='', prefix='tmp', dir=None):
        """
        Create a temporary file and return the file path.
        """
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
        os.close(fd)  # Close the file descriptor
        return path

    @staticmethod
    def remove_temp_file(file_path):
        """
        Remove Temp File.

        Remove the temp file.
        """
        if os.path.exists(file_path):
            os.remove(file_path)

    async def handle_file(self, request):
        """
        Handle File.

        Handle the file request.
        """
        filename = request.match_info.get('filename', None)
        if not filename:
            raise web.HTTPNotFound()
        # Sanitize the filename to prevent path traversal attacks
        filename = os.path.basename(filename)
        temp_dir = tempfile.gettempdir()
        file_path = Path(temp_dir).joinpath(filename)

        # Check if the file exists and is within the temp directory
        if not file_path.exists() or not file_path.is_file():
            return web.Response(status=404, text='File not found')

        # Ensure the file is actually within the temp directory
        if not str(file_path).startswith(str(Path(temp_dir))):
            return web.Response(status=403, text='Forbidden')

        return web.FileResponse(path=file_path)

    def setup(
        self,
        app: Union[WebApp, web.Application],
        route: str = 'data',
        base_url: str = None
    ) -> None:
        """
        Setup TempFileManager to be used as a static class.

        Args:
            app (web.Application): The aiohttp application.
            route (str): The route under which to serve the files.
            base_url (str): The base URL of the server.
        """
        if isinstance(app, BaseApplication):
            app = app.get_app()
        elif isinstance(app, WebApp):
            app = app  # register the app into the Extension

        self.app = app
        self.route = route
        self.base_url = base_url

        app["tempfile"] = self

        # set the routes with a wildcard route
        app.router.add_get(
            route + "/{filename}", self.handle_file
        )

    def get_file_url(self, temp_file_path, base_url=None):
        """
        Convert a temp file path into a URL of the web server.

        Args:
            temp_file_path (str): The path to the temporary file.
            base_url (str, optional): The base URL of the server.

        Returns:
            str: The URL to access the file.
        """
        filename = os.path.basename(temp_file_path)
        filename_encoded = quote(filename)
        if base_url is None:
            if self.base_url:
                base_url = self.base_url
            else:
                raise ValueError(
                    "Base URL is not set. add base_url on setup()."
                )
        # Ensure the route starts with '/'
        route = self.route if self.route.startswith('/') else '/' + self.route
        # Build the URL
        url = urljoin(
            base_url.rstrip('/') + '/', route.lstrip('/') + '/'
        )
        full_url = url + filename_encoded
        return full_url
