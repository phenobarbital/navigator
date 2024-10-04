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
from navconfig.logging import logging
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
        self.logger = logging.getLogger('storage.GCS')
        self.logger.info(
            f"Started GCSFileManager for bucket: {bucket_name}"
        )

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

    def upload_file_from_bytes(
        self,
        file_obj: bytes,
        destination_blob_name,
        content_type='application/zip'
    ):
        """
        Uploads data to the bucket from a file-like object.

        Args:
            file_obj (BytesIO): The file-like object containing the data to upload.
            destination_blob_name (str): The destination blob name in GCS.

        Returns:
            str: The blob name.
        """
        # Ensure the file pointer is at the beginning
        file_obj.seek(0)
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_file(file_obj, content_type=content_type)
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
        status: int = 200
    ):
        """
        Get a response object.

        Args:
            content_type (str, optional): The content type of the response.
            binary (bool, optional): if True, file is a octect stream.
        Returns:
            aiohttp.web.Response: The response object.
        """
        current = datetime.now(timezone.utc)
        expires = current + timedelta(days=7)
        last_modified = current - timedelta(hours=1)
        return web.StreamResponse(
            status=status,
            reason=reason,
            headers={
                "Pragma": "public",  # required,
                "Last-Modified": last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "Expires": expires.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "Connection": "keep-alive",
                "Cache-Control": "private",  # required for certain browsers,
                "Content-Description": "File Transfer",
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
        filename = request.match_info.get('filepath', None)

        if not filename:
            raise web.HTTPNotFound()

        # Sanitize the filename to prevent path traversal attacks
        try:
            filename = PurePath(filename).relative_to('/')
        except ValueError:
            pass
        blob = self.bucket.blob(filename)

        if not blob.exists():
            return web.Response(
                status=404,
                text='File not found'
            )

        # Get the blob size
        blob.reload()  # Fetch the latest blob metadata

        response = self.get_response()
        response.enable_chunked_encoding = False  # Disable chunked encoding
        response.content_length = blob.size  # Set the total content length

        file = os.path.basename(filename)
        response.headers['Content-Disposition'] = f'attachment; filename="{file}"'
        response.headers['Content-Type'] = blob.content_type or 'application/octet-stream'

        # Handle Range requests for partial content
        if 'Range' in request.headers:
            start, end = self.parse_range_header(
                request.headers['Range'], blob.size
            )
            response.content_length = end - start + 1
            response.set_status(206)  # Partial Content
            response.headers['Content-Range'] = f'bytes {start}-{end}/{blob.size}'
            blob_file = blob.open('rb')
            blob_file.seek(start)
        else:
            start = 0
            end = blob.size - 1
            blob_file = blob.open('rb')

        await response.prepare(request)

        # Stream the file in chunks to the client
        chunk_size = 1024 * 1024  # 1 MB
        while start <= end:
            chunk = blob_file.read(min(chunk_size, end - start + 1))
            if not chunk:
                break
            await response.write(chunk)
            start += len(chunk)

        blob_file.close()
        await response.write_eof()
        return response

    def parse_range_header(self, range_header, file_size):
        """
        Parses a Range header to get the start and end byte positions.

        Args:
            range_header (str): The Range header value.
            file_size (int): The total size of the file.

        Returns:
            tuple: A tuple containing the start and end byte positions.
        """
        try:
            unit, ranges = range_header.strip().split('=')
            if unit != 'bytes':
                raise ValueError('Invalid unit in Range header')
            start, end = ranges.split('-')
            start = int(start) if start else 0
            end = int(end) if end else file_size - 1
            if start > end or end >= file_size:
                raise ValueError('Invalid range in Range header')
            return start, end
        except (ValueError, IndexError) as e:
            raise web.HTTPBadRequest(reason=f'Invalid Range header: {e}')

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
            route + "/{filepath:.*}", self.handle_file
        )

    def get_file_url(
        self,
        blob_name,
        base_url=None,
        use_signed_url=False,
        expiration=3600
    ):
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
            url = blob.generate_signed_url(
                expiration=timedelta(seconds=expiration)
            )
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

    def find_files(self, keywords=None, extension=None, prefix=None):
        """
        Find files in the bucket based on keywords or extension.

        Args:
            keywords (str or list, optional): Keywords to search for in the file name.
            extension (str, optional): File extension to filter by (e.g., ".csv").
            prefix (str, optional): The prefix to filter by.

        Returns:
            list: A list of matching blob names.
        """
        blobs = self.bucket.list_blobs(prefix=prefix)
        matching_files = []

        for blob in blobs:
            if keywords:
                if isinstance(keywords, str):
                    keywords = [keywords]
                if not all(keyword in blob.name for keyword in keywords):
                    continue

            if extension:
                if not blob.name.endswith(extension):
                    continue

            matching_files.append(blob.name)

        return matching_files

    def create_folder(self, folder_name):
        """
        Create a "folder" in GCS (simulated by creating an empty object).

        Args:
            folder_name (str): The name of the folder to create.
                Should end with a slash ("/").
        """
        if not folder_name.endswith("/"):
            folder_name += "/"
        blob = self.bucket.blob(folder_name)
        blob.upload_from_string("")

    def remove_folder(self, folder_name):
        """
        Remove a "folder" in GCS (by deleting all objects with the prefix).

        Args:
            folder_name (str): The name of the folder to remove.
        """
        if not folder_name.endswith("/"):
            folder_name += "/"
        blobs = self.bucket.list_blobs(prefix=folder_name)
        for blob in blobs:
            blob.delete()

    def rename_folder(self, old_folder_name, new_folder_name):
        """
        Rename a "folder" in GCS (by renaming all objects with the prefix).

        Args:
            old_folder_name (str): The current name of the folder.
            new_folder_name (str): The new name for the folder.
        """
        if not old_folder_name.endswith("/"):
            old_folder_name += "/"
        if not new_folder_name.endswith("/"):
            new_folder_name += "/"

        blobs = self.bucket.list_blobs(prefix=old_folder_name)
        for blob in blobs:
            new_blob_name = blob.name.replace(old_folder_name, new_folder_name, 1)
            self.bucket.rename_blob(blob, new_blob_name)

    def rename_file(self, old_file_name, new_file_name):
        """
        Rename a file in GCS.

        Args:
            old_file_name (str): The current name of the file.
            new_file_name (str): The new name for the file.
        """
        blob = self.bucket.blob(old_file_name)
        self.bucket.rename_blob(blob, new_file_name)
