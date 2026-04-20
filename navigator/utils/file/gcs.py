"""
GCSFileManager.

Google Cloud Storage file manager implementing FileManagerInterface.
All GCS SDK calls are wrapped in asyncio.to_thread() to avoid blocking
the event loop (the google-cloud-storage SDK is synchronous).

Supports:
  - Resumable uploads (5MB threshold, 256KB chunks)
  - Three credential modes (dict, file path, google.auth.default())
  - Folder operations (create, remove, rename)
  - Signed URLs (v4) and app-served URLs
  - Prefix management
"""
import asyncio
import fnmatch
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path, PurePath
from typing import BinaryIO, List, Optional, Union
from urllib.parse import quote

import google.auth
from google.cloud import storage
from google.oauth2 import service_account
from navconfig.logging import logging

from .abstract import FileManagerInterface, FileMetadata


class GCSFileManager(FileManagerInterface):
    """Google Cloud Storage file manager with async-first design.

    Every GCS SDK call is executed via ``asyncio.to_thread()`` because
    the ``google-cloud-storage`` library is synchronous.

    Attributes:
        manager_name: Identifier used in app context registration.
        RESUMABLE_THRESHOLD: File size threshold for resumable uploads (5MB).
        CHUNK_SIZE: Chunk size for resumable uploads (256KB).
    """

    manager_name: str = "gcsfile"

    RESUMABLE_THRESHOLD: int = 5 * 1024 * 1024   # 5MB
    CHUNK_SIZE: int = 256 * 1024                  # 256KB

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "",
        json_credentials: Optional[dict] = None,
        credentials: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        project: Optional[str] = None,
        resumable_threshold: Optional[int] = None,
        **kwargs,
    ) -> None:
        """Initialize GCSFileManager.

        Credential modes (in priority order):
        1. ``json_credentials`` -- dict with service account JSON.
        2. ``credentials`` -- path to a service account JSON file.
        3. ``google.auth.default()`` -- Application Default Credentials.

        Args:
            bucket_name: GCS bucket name.
            prefix: Key prefix prepended to all operations.
            json_credentials: Service account credentials as a dict.
            credentials: Path to a service account JSON file.
            scopes: OAuth2 scopes. Defaults to cloud-platform.
            project: GCP project ID (used with ADC mode).
            resumable_threshold: Override default 5MB resumable threshold.
            **kwargs: Passed through for extensibility.
        """
        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.resumable_threshold = resumable_threshold or self.RESUMABLE_THRESHOLD
        self.logger = logging.getLogger("navigator.storage.GCS")
        self._project = project
        self._creds = None

        default_scopes = scopes or ["https://www.googleapis.com/auth/cloud-platform"]
        scoped_credentials = None

        if json_credentials:
            self._creds = service_account.Credentials.from_service_account_info(
                json_credentials
            )
        elif credentials:
            self._creds = service_account.Credentials.from_service_account_file(
                credentials
            )
        else:
            self._creds, self._project = google.auth.default(
                scopes=default_scopes
            )

        if scopes and self._creds:
            scoped_credentials = self._creds.with_scopes(scopes)

        self.client = storage.Client(
            credentials=scoped_credentials or self._creds,
            project=self._project,
        )
        self.bucket = self.client.bucket(bucket_name)

        self.logger.info(
            "GCSFileManager initialised for bucket=%s prefix=%r",
            bucket_name,
            self.prefix,
        )

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

    def _make_metadata(self, blob) -> FileMetadata:
        """Build FileMetadata from a GCS blob.

        Args:
            blob: A google.cloud.storage.Blob instance.

        Returns:
            FileMetadata instance.
        """
        key = self._unprefixed(blob.name)
        name = os.path.basename(key) or key
        content_type, _ = mimetypes.guess_type(name)
        return FileMetadata(
            name=name,
            path=key,
            size=blob.size or 0,
            content_type=blob.content_type or content_type,
            modified_at=blob.updated,
            url=blob.public_url if blob.public_url else None,
        )

    # ------------------------------------------------------------------ #
    # Abstract method implementations                                     #
    # ------------------------------------------------------------------ #

    async def list_files(
        self, path: str = "", pattern: str = "*"
    ) -> List[FileMetadata]:
        """List blobs in the bucket.

        Args:
            path: Key prefix to list (appended to manager prefix).
            pattern: Glob pattern for blob name filtering (default "*").

        Returns:
            List of FileMetadata for matching blobs.
        """

        def _list() -> List[FileMetadata]:
            prefix = self._prefixed(path)
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            results: List[FileMetadata] = []
            for blob in blobs:
                key = self._unprefixed(blob.name)
                name = os.path.basename(key) or key
                if not fnmatch.fnmatch(name, pattern):
                    continue
                results.append(self._make_metadata(blob))
            return results

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Generate a signed URL (v4) for a GCS blob.

        Args:
            path: Blob name (without manager prefix).
            expiry: Signed URL expiry in seconds (default 3600).

        Returns:
            Signed URL string.
        """

        def _url() -> str:
            key = self._prefixed(path)
            blob = self.bucket.blob(key)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiry),
                method="GET",
            )

        return await asyncio.to_thread(_url)

    async def upload_file(
        self, source: Union[BinaryIO, Path], destination: str
    ) -> FileMetadata:
        """Upload a file to GCS, using resumable upload for large files.

        Args:
            source: Local Path or open binary stream.
            destination: Target blob name (without manager prefix).

        Returns:
            FileMetadata for the uploaded blob.
        """
        key = self._prefixed(destination)
        name = os.path.basename(destination) or destination
        content_type, _ = mimetypes.guess_type(name)
        content_type = content_type or "application/octet-stream"

        if isinstance(source, Path):
            file_size = source.stat().st_size

            def _upload_path() -> None:
                chunk = self.CHUNK_SIZE if file_size >= self.resumable_threshold else None
                blob = self.bucket.blob(key, chunk_size=chunk)
                blob.upload_from_filename(str(source), content_type=content_type)

            await asyncio.to_thread(_upload_path)
            size = file_size
        else:
            data = source.read() if hasattr(source, "read") else bytes(source)
            size = len(data)

            def _upload_bytes() -> None:
                chunk = self.CHUNK_SIZE if size >= self.resumable_threshold else None
                blob = self.bucket.blob(key, chunk_size=chunk)
                blob.upload_from_string(data, content_type=content_type)

            await asyncio.to_thread(_upload_bytes)

        def _get_blob():
            b = self.bucket.blob(key)
            b.reload()
            return b

        blob = await asyncio.to_thread(_get_blob)
        return self._make_metadata(blob)

    async def download_file(
        self, source: str, destination: Union[Path, BinaryIO]
    ) -> Path:
        """Download a GCS blob to a local path or file-like object.

        Args:
            source: Blob name (without manager prefix).
            destination: Target local Path or open binary stream.

        Returns:
            Path where the file was written.
        """
        key = self._prefixed(source)

        if isinstance(destination, Path):
            destination.parent.mkdir(parents=True, exist_ok=True)

            def _download_to_file() -> None:
                blob = self.bucket.blob(key)
                blob.download_to_filename(str(destination))

            await asyncio.to_thread(_download_to_file)
            return destination
        else:
            def _download_to_stream() -> bytes:
                blob = self.bucket.blob(key)
                return blob.download_as_bytes()

            data = await asyncio.to_thread(_download_to_stream)
            destination.write(data)
            return Path(source)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy a GCS blob within the same bucket.

        Args:
            source: Source blob name (without manager prefix).
            destination: Destination blob name (without manager prefix).

        Returns:
            FileMetadata for the copied blob.
        """
        src_key = self._prefixed(source)
        dst_key = self._prefixed(destination)

        def _copy():
            src_blob = self.bucket.blob(src_key)
            new_blob = self.bucket.copy_blob(src_blob, self.bucket, dst_key)
            return new_blob

        new_blob = await asyncio.to_thread(_copy)
        return self._make_metadata(new_blob)

    async def delete_file(self, path: str) -> bool:
        """Delete a GCS blob.

        Args:
            path: Blob name (without manager prefix).

        Returns:
            True if deleted, False if the blob did not exist.
        """
        key = self._prefixed(path)

        def _delete() -> bool:
            blob = self.bucket.blob(key)
            if blob.exists():
                blob.delete()
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        """Check whether a GCS blob exists.

        Args:
            path: Blob name (without manager prefix).

        Returns:
            True if the blob exists.
        """
        key = self._prefixed(path)

        def _exists() -> bool:
            blob = self.bucket.blob(key)
            return blob.exists()

        return await asyncio.to_thread(_exists)

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Return metadata for a single GCS blob.

        Args:
            path: Blob name (without manager prefix).

        Returns:
            FileMetadata for the blob.

        Raises:
            FileNotFoundError: If the blob does not exist.
        """
        key = self._prefixed(path)

        def _meta():
            blob = self.bucket.blob(key)
            if not blob.exists():
                raise FileNotFoundError(f"GCS blob not found: {path!r}")
            blob.reload()
            return blob

        blob = await asyncio.to_thread(_meta)
        return self._make_metadata(blob)

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create or overwrite a GCS blob with raw bytes.

        Args:
            path: Blob name (without manager prefix).
            content: Raw bytes to upload.

        Returns:
            True on success.
        """
        key = self._prefixed(path)
        content_type, _ = mimetypes.guess_type(os.path.basename(path))

        def _create() -> None:
            blob = self.bucket.blob(key)
            blob.upload_from_string(
                content, content_type=content_type or "application/octet-stream"
            )

        await asyncio.to_thread(_create)
        return True

    # ------------------------------------------------------------------ #
    # GCS-specific folder operations                                      #
    # ------------------------------------------------------------------ #

    async def create_folder(self, folder_name: str) -> None:
        """Create a GCS "folder" by uploading an empty placeholder blob.

        Args:
            folder_name: Folder name (trailing / will be added if missing).
        """
        if not folder_name.endswith("/"):
            folder_name += "/"

        def _create_folder() -> None:
            blob = self.bucket.blob(self._prefixed(folder_name))
            blob.upload_from_string("")

        await asyncio.to_thread(_create_folder)

    async def remove_folder(self, folder_name: str) -> None:
        """Remove a GCS "folder" by deleting all blobs with its prefix.

        Args:
            folder_name: Folder name (trailing / will be added if missing).
        """
        if not folder_name.endswith("/"):
            folder_name += "/"
        prefix = self._prefixed(folder_name)

        def _remove_folder() -> None:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            for blob in blobs:
                blob.delete()

        await asyncio.to_thread(_remove_folder)

    async def rename_folder(
        self, old_folder_name: str, new_folder_name: str
    ) -> None:
        """Rename a GCS "folder" by renaming all blobs with its prefix.

        Args:
            old_folder_name: Current folder name.
            new_folder_name: New folder name.
        """
        if not old_folder_name.endswith("/"):
            old_folder_name += "/"
        if not new_folder_name.endswith("/"):
            new_folder_name += "/"
        old_prefix = self._prefixed(old_folder_name)
        new_prefix = self._prefixed(new_folder_name)

        def _rename_folder() -> None:
            blobs = list(self.bucket.list_blobs(prefix=old_prefix))
            for blob in blobs:
                new_name = blob.name.replace(old_prefix, new_prefix, 1)
                self.bucket.rename_blob(blob, new_name)

        await asyncio.to_thread(_rename_folder)

    async def rename_file(self, old_file_name: str, new_file_name: str) -> None:
        """Rename a GCS blob.

        Args:
            old_file_name: Current blob name (without manager prefix).
            new_file_name: New blob name (without manager prefix).
        """
        old_key = self._prefixed(old_file_name)
        new_key = self._prefixed(new_file_name)

        def _rename() -> None:
            blob = self.bucket.blob(old_key)
            self.bucket.rename_blob(blob, new_key)

        await asyncio.to_thread(_rename)

    # ------------------------------------------------------------------ #
    # Override find_files with server-side prefix filtering               #
    # ------------------------------------------------------------------ #

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """Find GCS blobs by keyword(s), extension, and/or prefix.

        Args:
            keywords: Substring(s) that must appear in the blob name.
            extension: File extension to filter by (e.g. ".csv").
            prefix: Blob name prefix to restrict the search scope.

        Returns:
            List of matching FileMetadata objects.
        """

        def _find() -> List[FileMetadata]:
            server_prefix = self._prefixed(prefix or "")
            blobs = list(self.bucket.list_blobs(prefix=server_prefix))
            results: List[FileMetadata] = []
            for blob in blobs:
                key = self._unprefixed(blob.name)
                name = os.path.basename(key) or key
                if extension and not name.endswith(extension):
                    continue
                if keywords:
                    kw_list: List[str] = (
                        [keywords] if isinstance(keywords, str) else list(keywords)
                    )
                    if not all(kw in name for kw in kw_list):
                        continue
                results.append(self._make_metadata(blob))
            return results

        return await asyncio.to_thread(_find)

    # ------------------------------------------------------------------ #
    # Backward-compatible web-serving helpers                             #
    # ------------------------------------------------------------------ #

    def setup(self, app, route: str = "data", base_url: str = None):
        """Set up web-serving for this manager (backward compat).

        Delegates to FileServingExtension.

        Args:
            app: aiohttp Application or BaseApplication.
            route: URL prefix (default ``"data"``).
            base_url: Ignored (kept for signature compat).

        Returns:
            The configured app.
        """
        from .web import FileServingExtension

        ext = FileServingExtension(
            manager=self,
            route=route if route.startswith("/") else "/" + route,
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
