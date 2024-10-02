"""
GCSFileManager.

Exposing Files stored in Google Cloud Storage as static File Manager.
"""

from typing import Union
import os
from urllib.parse import quote, urljoin
from aiohttp import web
from google.cloud import storage
from ..types import WebApp
from ..applications.base import BaseApplication
from datetime import timedelta


class GCSFileManager:
    """
    GCSFileManager class.

    Exposing Files stored in Google Cloud Storage as static File Manager.
    """

    def __init__(self, bucket_name, credentials=None):
        """
        Initialize the GCSFileManager.

        Args:
            bucket_name (str): The name of the GCS bucket.
            credentials (google.auth.credentials.Credentials, optional): The credentials to use.
        """
        self.app = None
        self.route = '/data'
        self.base_url = None
        self.bucket_name = bucket_name
        self.client = storage.Client(credentials=credentials)
        self.bucket = self.client.bucket(bucket_name)

    def upload_file(self, source_file_path, destination_blob_name):
        """
        Uploads a file to the bucket.

        Args:
            source_file_path (str): The path to the file to upload.
            destination_blob_name (str): The destination blob name in GCS.

        Returns:
            str: The blob name.
        """
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_path)
        return destination_blob_name

    def upload_file_from_string(self, data, destination_blob_name):
        """
        Uploads data to the bucket from a string or bytes object.

        Args:
            data (str or bytes): The data to upload.
            destination_blob_name (str): The destination blob name in GCS.

        Returns:
            str: The blob name.
        """
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_string(data)
        return destination_blob_name

    def delete_file(self, blob_name):
        """
        Deletes a blob from the bucket.

        Args:
            blob_name (str): The name of the blob to delete.
        """
        blob = self.bucket.blob(blob_name)
        blob.delete()

    async def handle_file(self, request):
        """
        Handle the file request by streaming the file from GCS to the client.

        Args:
            request (aiohttp.web.Request): The incoming request.

        Returns:
            aiohttp.web.StreamResponse: The streaming response.
        """
        filename = request.match_info.get('filename', None)
        if not filename:
            raise web.HTTPNotFound()

        # Sanitize the filename to prevent path traversal attacks
        filename = os.path.basename(filename)
        blob = self.bucket.blob(filename)

        if not blob.exists():
            return web.Response(status=404, text='File not found')

        response = web.StreamResponse()
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = blob.content_type or 'application/octet-stream'
        await response.prepare(request)

        # Stream the file in chunks to the client
        chunk_size = 1024 * 1024  # 1 MB
        with blob.open('rb') as blob_file:
            while True:
                chunk = blob_file.read(chunk_size)
                if not chunk:
                    break
                await response.write(chunk)
        await response.write_eof()
        return response

    def setup(
        self,
        app: Union[WebApp, web.Application],
        route: str = 'data',
        base_url: str = None
    ) -> None:
        """
        Setup GCSFileManager to be used as a static class.

        Args:
            app (web.Application): The aiohttp application.
            route (str): The route under which to serve the files.
            base_url (str): The base URL of the server.
        """
        if isinstance(app, BaseApplication):
            app = app.get_app()
        elif isinstance(app, WebApp):
            app = app

        self.app = app
        self.route = route
        self.base_url = base_url

        app["gcsfile"] = self

        # Set the route with a wildcard
        app.router.add_get(
            route + "/{filename}", self.handle_file
        )

    def get_file_url(self, blob_name, base_url=None, use_signed_url=False, expiration=3600):
        """
        Generate a URL to access the file.

        Args:
            blob_name (str): The name of the blob.
            base_url (str, optional): The base URL of the server.
            use_signed_url (bool, optional): If True, generate a signed GCS URL.
            expiration (int, optional): Time in seconds for the signed URL to expire.

        Returns:
            str: The URL to access the file.
        """
        if use_signed_url:
            # Generate a signed URL to GCS
            blob = self.bucket.blob(blob_name)
            url = blob.generate_signed_url(expiration=timedelta(seconds=expiration))
            return url
        else:
            # Generate a URL to serve the file via the web application
            filename_encoded = quote(blob_name)
            if base_url is None:
                if self.base_url:
                    base_url = self.base_url
                else:
                    raise ValueError(
                        "Base URL is not set. Please provide base_url in setup()."
                    )
            # Ensure the route starts with '/'
            route = self.route if self.route.startswith('/') else '/' + self.route
            # Build the URL
            url = urljoin(
                base_url.rstrip('/') + '/', route.lstrip('/') + '/'
            )
            full_url = url + filename_encoded
            return full_url
