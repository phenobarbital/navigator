"""
S3FileManager.

AWS S3 file manager implementing FileManagerInterface.
Supports multipart uploads (100MB threshold, 10MB chunks, semaphore-based concurrency),
paginated listing, presigned URLs, and configurable credentials.
"""
import asyncio
import contextlib
import mimetypes
import os
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path, PurePath
from typing import BinaryIO, List, Optional, Union

import aioboto3
from botocore.exceptions import ClientError
from navconfig.logging import logging

from ... import conf as _nav_conf

# AWS_CREDENTIALS may not be defined in every environment (e.g. testing).
# Use getattr so that test suites can patch this module-level variable directly
# via patch.object(navigator.utils.file.s3, "AWS_CREDENTIALS", ...) without
# requiring the production settings file to be present.
AWS_CREDENTIALS: dict = getattr(_nav_conf, "AWS_CREDENTIALS", {})

from .abstract import FileManagerInterface, FileMetadata


logging.getLogger(name="botocore").setLevel(logging.WARNING)


class S3FileManager(FileManagerInterface):
    """AWS S3 file manager with async-first design.

    Uses ``aioboto3`` for native async S3 calls (no ``asyncio.to_thread()``
    needed).  Multipart uploads are triggered automatically for files above
    ``multipart_threshold`` bytes.

    Attributes:
        manager_name: Identifier used in app context registration.
        MULTIPART_THRESHOLD: Default threshold for multipart upload (100MB).
        MULTIPART_CHUNKSIZE: Default chunk size for multipart upload (10MB).
        MAX_CONCURRENCY: Default max concurrent part uploads.
    """

    manager_name: str = "s3file"

    MULTIPART_THRESHOLD: int = 100 * 1024 * 1024  # 100MB
    MULTIPART_CHUNKSIZE: int = 10 * 1024 * 1024   # 10MB
    MAX_CONCURRENCY: int = 10

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        prefix: str = "",
        multipart_threshold: Optional[int] = None,
        multipart_chunksize: Optional[int] = None,
        max_concurrency: Optional[int] = None,
        **kwargs,
    ) -> None:
        """Initialize the S3FileManager.

        Credentials are resolved in this priority:
        1. Constructor ``credentials`` kwarg (dict with aws_key/aws_secret).
        2. ``AWS_CREDENTIALS[aws_id]`` from navigator.conf.
        3. ``AWS_CREDENTIALS["default"]``.

        Args:
            bucket_name: S3 bucket name. Falls back to credential dict.
            aws_id: Key into AWS_CREDENTIALS (default ``"default"``).
            region_name: AWS region override.
            prefix: Key prefix prepended to all operations.
            multipart_threshold: Override default 100MB threshold.
            multipart_chunksize: Override default 10MB chunk size.
            max_concurrency: Override default 10 concurrent parts.
            **kwargs: May contain ``credentials`` dict with aws_key/aws_secret.
        """
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.multipart_threshold = multipart_threshold or self.MULTIPART_THRESHOLD
        self.multipart_chunksize = multipart_chunksize or self.MULTIPART_CHUNKSIZE
        self.max_concurrency = max_concurrency or self.MAX_CONCURRENCY
        self.logger = logging.getLogger("navigator.storage.S3")

        # Resolve credentials
        explicit_creds = kwargs.get("credentials", None)
        if explicit_creds:
            creds = explicit_creds
        else:
            creds = AWS_CREDENTIALS.get(aws_id) or AWS_CREDENTIALS.get("default")

        if not creds:
            raise ValueError(
                f"AWS credentials not found for aws_id={aws_id!r}. "
                "Provide credentials kwarg or configure AWS_CREDENTIALS."
            )

        self.aws_config = {
            "aws_access_key_id": creds["aws_key"],
            "aws_secret_access_key": creds["aws_secret"],
            "region_name": region_name or creds.get("region_name", "us-east-1"),
        }
        self.bucket_name = bucket_name or creds.get("bucket_name")

        self.logger.info(
            "S3FileManager initialised for bucket=%s region=%s",
            self.bucket_name,
            self.aws_config["region_name"],
        )
        self.session = aioboto3.Session()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _prefixed(self, key: str) -> str:
        """Return the key with the manager prefix applied."""
        return self.prefix + key.lstrip("/")

    def _unprefixed(self, key: str) -> str:
        """Strip the manager prefix from a key."""
        if self.prefix and key.startswith(self.prefix):
            return key[len(self.prefix):]
        return key

    def _make_metadata(self, key: str, obj: dict) -> FileMetadata:
        """Build FileMetadata from an S3 list-objects entry.

        Args:
            key: The S3 object key (with prefix stripped).
            obj: The S3 object dict from list_objects_v2.

        Returns:
            FileMetadata instance.
        """
        name = os.path.basename(key) or key
        content_type, _ = mimetypes.guess_type(name)
        return FileMetadata(
            name=name,
            path=key,
            size=obj.get("Size", 0),
            content_type=content_type,
            modified_at=obj.get("LastModified"),
            url=None,
        )

    async def _s3_client(self):
        """Async context manager that yields a configured S3 client."""
        return self.session.client(
            "s3",
            aws_access_key_id=self.aws_config["aws_access_key_id"],
            aws_secret_access_key=self.aws_config["aws_secret_access_key"],
            region_name=self.aws_config["region_name"],
        )

    # ------------------------------------------------------------------ #
    # Abstract method implementations                                     #
    # ------------------------------------------------------------------ #

    async def list_files(
        self, path: str = "", pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files in the bucket with optional prefix and pattern.

        Args:
            path: Key prefix to list (appended to manager prefix).
            pattern: Glob pattern for filename filtering (default ``"*"``).

        Returns:
            List of FileMetadata for matching objects.
        """
        import fnmatch

        prefix = self._prefixed(path)
        results: List[FileMetadata] = []
        async with await self._s3_client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self.bucket_name, Prefix=prefix
            ):
                for obj in page.get("Contents", []):
                    key = self._unprefixed(obj["Key"])
                    name = os.path.basename(key) or key
                    if not fnmatch.fnmatch(name, pattern):
                        continue
                    results.append(self._make_metadata(key, obj))
        return results

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Generate a presigned URL for an S3 object.

        Args:
            path: Object key (without manager prefix).
            expiry: Presigned URL expiry in seconds (default 3600).

        Returns:
            Presigned URL string.
        """
        key = self._prefixed(path)
        async with await self._s3_client() as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiry,
            )
        return url

    async def upload_file(
        self, source: Union[BinaryIO, Path], destination: str
    ) -> FileMetadata:
        """Upload a file to S3, using multipart for large files.

        Args:
            source: Local Path or open binary stream.
            destination: Target S3 key (without manager prefix).

        Returns:
            FileMetadata for the uploaded object.
        """
        key = self._prefixed(destination)
        name = os.path.basename(destination) or destination
        content_type, _ = mimetypes.guess_type(name)
        content_type = content_type or "application/octet-stream"

        if isinstance(source, Path):
            file_size = source.stat().st_size
            if file_size >= self.multipart_threshold:
                await self._multipart_upload_path(source, key, content_type)
            else:
                async with await self._s3_client() as s3:
                    await s3.upload_file(
                        str(source),
                        self.bucket_name,
                        key,
                        ExtraArgs={"ContentType": content_type},
                    )
            size = file_size
            modified_at = datetime.fromtimestamp(source.stat().st_mtime)
        else:
            data = source.read() if hasattr(source, "read") else source
            size = len(data)
            if size >= self.multipart_threshold:
                await self._multipart_upload_bytes(data, key, content_type)
            else:
                async with await self._s3_client() as s3:
                    await s3.put_object(
                        Bucket=self.bucket_name,
                        Key=key,
                        Body=data,
                        ContentType=content_type,
                    )
            modified_at = datetime.utcnow()

        return FileMetadata(
            name=name,
            path=self._unprefixed(key),
            size=size,
            content_type=content_type,
            modified_at=modified_at,
            url=None,
        )

    async def _multipart_upload_path(
        self, source: Path, key: str, content_type: str
    ) -> None:
        """Perform a multipart upload from a local file.

        Args:
            source: Path to the local file.
            key: S3 key (with prefix already applied).
            content_type: MIME type for the object.
        """
        async with await self._s3_client() as s3:
            mpu = await s3.create_multipart_upload(
                Bucket=self.bucket_name, Key=key, ContentType=content_type
            )
            upload_id = mpu["UploadId"]
            parts: List[dict] = []
            semaphore = asyncio.Semaphore(self.max_concurrency)

            try:
                with open(source, "rb") as fh:
                    part_number = 1
                    tasks = []
                    while True:
                        chunk = fh.read(self.multipart_chunksize)
                        if not chunk:
                            break

                        async def _upload_part(
                            data: bytes, pnum: int, s3_client=s3
                        ) -> dict:
                            async with semaphore:
                                resp = await s3_client.upload_part(
                                    Bucket=self.bucket_name,
                                    Key=key,
                                    UploadId=upload_id,
                                    PartNumber=pnum,
                                    Body=data,
                                )
                                return {"PartNumber": pnum, "ETag": resp["ETag"]}

                        tasks.append(_upload_part(chunk, part_number))
                        part_number += 1

                    parts = await asyncio.gather(*tasks)

                parts_sorted = sorted(parts, key=lambda x: x["PartNumber"])
                await s3.complete_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts_sorted},
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await s3.abort_multipart_upload(
                        Bucket=self.bucket_name, Key=key, UploadId=upload_id
                    )
                raise

    async def _multipart_upload_bytes(
        self, data: bytes, key: str, content_type: str
    ) -> None:
        """Perform a multipart upload from raw bytes.

        Args:
            data: Raw bytes to upload.
            key: S3 key (with prefix already applied).
            content_type: MIME type for the object.
        """
        async with await self._s3_client() as s3:
            mpu = await s3.create_multipart_upload(
                Bucket=self.bucket_name, Key=key, ContentType=content_type
            )
            upload_id = mpu["UploadId"]
            parts: List[dict] = []
            semaphore = asyncio.Semaphore(self.max_concurrency)

            try:
                tasks = []
                offset = 0
                part_number = 1
                while offset < len(data):
                    chunk = data[offset: offset + self.multipart_chunksize]
                    offset += self.multipart_chunksize

                    async def _upload_part(
                        d: bytes, pnum: int, s3_client=s3
                    ) -> dict:
                        async with semaphore:
                            resp = await s3_client.upload_part(
                                Bucket=self.bucket_name,
                                Key=key,
                                UploadId=upload_id,
                                PartNumber=pnum,
                                Body=d,
                            )
                            return {"PartNumber": pnum, "ETag": resp["ETag"]}

                    tasks.append(_upload_part(chunk, part_number))
                    part_number += 1

                parts = await asyncio.gather(*tasks)
                parts_sorted = sorted(parts, key=lambda x: x["PartNumber"])
                await s3.complete_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts_sorted},
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await s3.abort_multipart_upload(
                        Bucket=self.bucket_name, Key=key, UploadId=upload_id
                    )
                raise

    async def download_file(
        self, source: str, destination: Union[Path, BinaryIO]
    ) -> Path:
        """Download an S3 object to a local path or file-like object.

        Args:
            source: S3 key (without manager prefix).
            destination: Target local Path or open binary stream.

        Returns:
            Path where the file was written (or a synthetic Path for streams).
        """
        key = self._prefixed(source)
        async with await self._s3_client() as s3:
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                await s3.download_file(self.bucket_name, key, str(destination))
                return destination
            else:
                response = await s3.get_object(Bucket=self.bucket_name, Key=key)
                async with response["Body"] as stream:
                    data = await stream.read()
                destination.write(data)
                return Path(source)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy an S3 object within the same bucket.

        Args:
            source: Source S3 key (without manager prefix).
            destination: Destination S3 key (without manager prefix).

        Returns:
            FileMetadata for the copied object.
        """
        src_key = self._prefixed(source)
        dst_key = self._prefixed(destination)
        async with await self._s3_client() as s3:
            await s3.copy_object(
                CopySource={"Bucket": self.bucket_name, "Key": src_key},
                Bucket=self.bucket_name,
                Key=dst_key,
            )
            head = await s3.head_object(Bucket=self.bucket_name, Key=dst_key)

        name = os.path.basename(destination) or destination
        content_type, _ = mimetypes.guess_type(name)
        return FileMetadata(
            name=name,
            path=self._unprefixed(dst_key),
            size=head.get("ContentLength", 0),
            content_type=content_type or head.get("ContentType"),
            modified_at=head.get("LastModified"),
            url=None,
        )

    async def delete_file(self, path: str) -> bool:
        """Delete an S3 object.

        Args:
            path: S3 key (without manager prefix).

        Returns:
            True after deletion (S3 delete is idempotent).
        """
        key = self._prefixed(path)
        async with await self._s3_client() as s3:
            await s3.delete_object(Bucket=self.bucket_name, Key=key)
        return True

    async def exists(self, path: str) -> bool:
        """Check whether an S3 object exists.

        Args:
            path: S3 key (without manager prefix).

        Returns:
            True if the object exists.
        """
        key = self._prefixed(path)
        try:
            async with await self._s3_client() as s3:
                await s3.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Return metadata for a single S3 object.

        Args:
            path: S3 key (without manager prefix).

        Returns:
            FileMetadata for the object.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        key = self._prefixed(path)
        try:
            async with await self._s3_client() as s3:
                head = await s3.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"S3 object not found: {path!r}")
            raise

        name = os.path.basename(path) or path
        content_type, _ = mimetypes.guess_type(name)
        return FileMetadata(
            name=name,
            path=self._unprefixed(key),
            size=head.get("ContentLength", 0),
            content_type=content_type or head.get("ContentType"),
            modified_at=head.get("LastModified"),
            url=None,
        )

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create or overwrite an S3 object with raw bytes.

        Args:
            path: S3 key (without manager prefix).
            content: Raw bytes to upload.

        Returns:
            True on success.
        """
        key = self._prefixed(path)
        content_type, _ = mimetypes.guess_type(os.path.basename(path))
        async with await self._s3_client() as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type or "application/octet-stream",
            )
        return True

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """Find S3 objects by keyword(s) and/or extension.

        Uses a server-side prefix filter combined with client-side
        keyword/extension filtering.

        Args:
            keywords: Substring(s) that must appear in the object name.
            extension: File extension to filter by (e.g. ``".csv"``).
            prefix: Key prefix to restrict the search scope.

        Returns:
            List of matching FileMetadata objects.
        """
        server_prefix = self._prefixed(prefix or "")
        results: List[FileMetadata] = []
        async with await self._s3_client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self.bucket_name, Prefix=server_prefix
            ):
                for obj in page.get("Contents", []):
                    key = self._unprefixed(obj["Key"])
                    name = os.path.basename(key) or key
                    if extension and not name.endswith(extension):
                        continue
                    if keywords:
                        kw_list: List[str] = (
                            [keywords]
                            if isinstance(keywords, str)
                            else list(keywords)
                        )
                        if not all(kw in name for kw in kw_list):
                            continue
                    results.append(self._make_metadata(key, obj))
        return results

    # ------------------------------------------------------------------ #
    # Backward-compatible web-serving helpers                             #
    # ------------------------------------------------------------------ #

    def setup(self, app, route: str = "/data", base_url: str = None):
        """Set up web-serving for this manager (backward compat).

        Delegates to FileServingExtension.

        Args:
            app: aiohttp Application or BaseApplication.
            route: URL prefix (default ``"/data"``).
            base_url: Ignored (kept for signature compat).

        Returns:
            The configured app.
        """
        from .web import FileServingExtension

        ext = FileServingExtension(
            manager=self,
            route=route,
            manager_name=self.manager_name,
        )
        return ext.setup(app)

    async def handle_file(self, request):
        """Handle a file request (backward compat).

        Delegates to FileServingExtension.

        Args:
            request: aiohttp Request.

        Returns:
            StreamResponse.
        """
        from .web import FileServingExtension

        ext = FileServingExtension(manager=self, manager_name=self.manager_name)
        return await ext.handle_file(request)
