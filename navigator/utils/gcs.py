"""
GCSFileManager.

Exposing Files stored in Google Cloud Storage as static File Manager.
"""
from typing import Union, Any
import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePath, Path
from urllib.parse import quote, urljoin
from aiohttp import web
import google.auth
from google.cloud import storage
from google.oauth2 import service_account
from ..types import WebApp
from ..applications.base import BaseApplication


class GCSFileManager:
    """
    GCSFileManager class.

    Exposing Files stored in Google Cloud Storage as static File Manager.
    """

    def __init__(
        self,
        bucket_name: str,
        route: str = '/data',
        **kwargs
    ):
        """
        Initialize the GCSFileManager.

        Args:
            bucket_name (str): The name of the GCS bucket.
            credentials (google.auth.credentials.Credentials, optional):
            The credentials to use.
        """
        self.app = None
        self.route = route
        self.base_url = None
        self.bucket_name = bucket_name
        self.credentials = None
        self.project = None
        json_credentials = kwargs.get('json_credentials', None)
        credentials = kwargs.get('credentials', None)
        # Example Scope: ['https://www.googleapis.com/auth/cloud-platform']
        self.scopes: list = kwargs.get('scopes', None)
        scoped_credentials = None
        if json_credentials:
            # Using Json:
            self.credentials = service_account.Credentials.from_service_account_info(
                json_credentials
            )
        elif credentials:
            # Using File
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials
            )
        else:
            self.credentials, self.project = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        if self.scopes:
            scoped_credentials = self.credentials.with_scopes(
                self.scopes
            )
        # Initialize the GCS client
        if scoped_credentials:
            self.client = storage.Client(credentials=scoped_credentials)
        else:
            self.client = storage.Client(credentials=self.credentials)
        self.bucket = self.client.bucket(bucket_name)

    def list_all_files(self, prefix=None):
        """
        List all files in the bucket.

        Args:
            prefix (str, optional): The prefix to filter by.

        Returns:
            list: A list of blob names.
        """
        blobs = self.bucket.list_blobs(prefix=prefix)
        return blobs

    def list_files(self, prefix=None):
        """
        List files in the bucket.

        Args:
            prefix (str, optional): The prefix to filter by.

        Returns:
            list: A list of blob names.
        """
        blobs = self.bucket.list_blobs(prefix=prefix)
        return [blob.name for blob in blobs]

    def upload_file(
        self,
        source_file_path,
        destination_blob_name: Union[str, PurePath] = None
    ):
        """
        Uploads a file to the bucket.

        Args:
            source_file_path (str): The path to the file to upload.
            destination_blob_name (str): The destination blob name in GCS.

        Returns:
            str: The blob name.
        """
        if isinstance(source_file_path, PurePath) and destination_blob_name is None:
            destination_blob_name = str(source_file_path.name)
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_path)
        return destination_blob_name

    def upload_file_from_string(self, data: Any, destination_blob_name):
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

    def get_response(
        self,
        reason: str = 'OK',
        status: int = 200,
        content_type: str = 'text/html',
        binary: bool = True
    ):
        """
        Get a response object.

        Args:
            content_type (str, optional): The content type of the response.
            binary (bool, optional): if True, file is a octect stream.
        Returns:
            aiohttp.web.Response: The response object.
        """
        if binary is True:
            content_type = 'application/octet-stream'
        current = datetime.now(timezone.utc)
        expires = current + timedelta(days=7)
        last_modified = current - timedelta(hours=1)
        return web.Response(
            status=status,
            reason=reason,
            content_type=content_type,
            headers={
                "Pragma": "public",  # required,
                "Last-Modified": last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "Expires": expires.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "Connection": "keep-alive",
                "Cache-Control": "private",  # required for certain browsers,
                "Content-Description": "File Transfer",
                "Content-Type": content_type,
                "Content-Transfer-Encoding": "binary",
                "Date": current.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            },
        )

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
            return web.Response(
                status=404,
                text='File not found'
            )

        response = self.get_response()
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
