"""
S3FileManager.

Exposing Files stored in AWS S3 asynchronously using aioboto3.
"""
from typing import Union
import os
from pathlib import PurePath
from aiohttp import web
import aioboto3
from navconfig.logging import logging
from ...types import WebApp
from ...conf import AWS_CREDENTIALS
from ...applications.base import BaseApplication

class S3FileManager:
    """
    S3FileManager class.

    Exposing Files stored in AWS S3 as a static File Manager with asyncio support.
    """

    def __init__(self, bucket_name: str, route: str = '/data', aws_id: str = 'default', **kwargs):
        """
        Initialize the S3FileManager.

        Args:
            bucket_name (str): The name of the S3 bucket.
            aws_id (str): Identifier for AWS credentials.
        """
        self.app = None
        self.route = route
        self.base_url = None
        self.bucket_name = bucket_name

        credentials = AWS_CREDENTIALS.get(aws_id, 'default')
        if not credentials:
            raise ValueError(
                "AWS credentials not found for the provided ID."
            )

        self.aws_config = {
            "aws_access_key_id": credentials["aws_key"],
            "aws_secret_access_key": credentials["aws_secret"],
            "region_name": credentials.get("region_name", "us-east-1"),
        }

        self.logger = logging.getLogger('storage.S3')
        self.logger.info(f"Started S3FileManager for bucket: {bucket_name}")

    async def list_files(self, prefix: str = None) -> list:
        """
        List files in the bucket.

        Args:
            prefix (str, optional): The prefix to filter by.

        Returns:
            list: A list of object keys.
        """
        async with aioboto3.client('s3', **self.aws_config) as s3_client:
            paginator = s3_client.get_paginator('list_objects_v2')
            async for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get('Contents', []):
                    yield obj['Key']

    async def upload_file(self, source_file_path: str, destination_key: str):
        """
        Uploads a file to the bucket.

        Args:
            source_file_path (str): The local path to the file.
            destination_key (str): The destination key in S3.

        Returns:
            str: The destination key.
        """
        async with aioboto3.client('s3', **self.aws_config) as s3_client:
            await s3_client.upload_file(source_file_path, self.bucket_name, destination_key)
        return destination_key

    async def upload_file_from_bytes(
        self,
        file_obj: bytes,
        destination_key: str,
        content_type='application/octet-stream'
    ):
        """
        Uploads a file-like object to S3.

        Args:
            file_obj (bytes): The file-like object.
            destination_key (str): The destination key in S3.
            content_type (str, optional): The content type of the file.

        Returns:
            str: The destination key.
        """
        async with aioboto3.client('s3', **self.aws_config) as s3_client:
            await s3_client.put_object(
                Bucket=self.bucket_name,
                Key=destination_key,
                Body=file_obj,
                ContentType=content_type
            )
        return destination_key

    async def delete_file(self, key: str):
        """
        Deletes a file from the bucket.

        Args:
            key (str): The key of the object to delete.
        """
        async with aioboto3.client('s3', **self.aws_config) as s3_client:
            await s3_client.delete_object(Bucket=self.bucket_name, Key=key)

    async def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for the file.

        Args:
            key (str): The key of the object.
            expiration (int, optional): Time in seconds for the URL to expire.

        Returns:
            str: The presigned URL.
        """
        async with aioboto3.client('s3', **self.aws_config) as s3_client:
            url = await s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
        return url

    async def find_files(
        self,
        keywords: Union[str, list] = None,
        extension: str = None,
        prefix: str = None
    ) -> list:
        """
        Find files based on keywords or extensions.

        Args:
            keywords (Union[str, list], optional): Keywords to search for in filenames.
            extension (str, optional): File extension to filter by.
            prefix (str, optional): The prefix to filter by.

        Returns:
            list: A list of matching object keys.
        """
        matching_files = []
        async for file in self.list_files(prefix):
            if keywords:
                if isinstance(keywords, str):
                    keywords = [keywords]
                if not all(keyword in file for keyword in keywords):
                    continue

            if extension and not file.endswith(extension):
                continue

            matching_files.append(file)

        return matching_files

    async def handle_file(self, request):
        """
        Handle file requests by streaming the file from S3.

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

        try:
            async with aioboto3.client('s3', **self.aws_config) as s3_client:
                response = await s3_client.get_object(Bucket=self.bucket_name, Key=str(filename))
                data_stream = response['Body']
                content_length = response['ContentLength']
                content_type = response.get('ContentType', 'application/octet-stream')

                stream_response = web.StreamResponse(
                    status=200,
                    reason='OK',
                    headers={
                        "Content-Disposition": f"attachment; filename={os.path.basename(filename)}",
                        "Content-Type": content_type,
                        "Content-Length": str(content_length),
                    },
                )
                await stream_response.prepare(request)
                chunk_size = 1024 * 1024  # 1MB
                while True:
                    chunk = await data_stream.read(chunk_size)
                    if not chunk:
                        break
                    await stream_response.write(chunk)

                await stream_response.write_eof()
                return stream_response
        except Exception:
            return web.Response(status=404, text="File not found")

    def setup(self, app: Union[WebApp, web.Application], route: str = '/data', base_url: str = None):
        """
        Setup S3FileManager to integrate with an aiohttp application.

        Args:
            app (aiohttp.web.Application): The aiohttp application.
            route (str): The route under which to serve files.
            base_url (str): The base URL of the application.
        """
        if isinstance(app, BaseApplication):
            app = app.get_app()
        elif isinstance(app, WebApp):
            app = app

        self.app = app
        self.route = route
        self.base_url = base_url

        app["s3file"] = self

        app.router.add_get(route + "/{filepath:.*}", self.handle_file)
