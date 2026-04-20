"""
TempFileManager.

Temporary file manager with auto-cleanup on context-manager exit,
process exit (atexit), and garbage collection (__del__).

Implements FileManagerInterface — all operations are sandboxed to the
system temp directory.
"""
import asyncio
import atexit
import contextlib
import fnmatch
import mimetypes
import os
import shutil
import tempfile
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO, List, Optional, Union

from navconfig.logging import logging

from .abstract import FileManagerInterface, FileMetadata


class TempFileManager(FileManagerInterface):
    """Temporary file manager sandboxed to a dedicated temp directory.

    Files are auto-cleaned on context-manager exit, interpreter shutdown
    (``atexit``), or garbage collection (``__del__``).

    Attributes:
        manager_name: Identifier used in app context registration.
        prefix: Prefix for the temp directory name.
        cleanup_on_exit: Whether to register atexit cleanup handler.
        cleanup_on_delete: Whether to clean on __del__.
    """

    manager_name: str = "tempfile"

    def __init__(
        self,
        prefix: str = "navigator_",
        cleanup_on_exit: bool = True,
        cleanup_on_delete: bool = True,
    ) -> None:
        """Initialize TempFileManager and create the temp directory.

        Args:
            prefix: Prefix for the temp directory name (default ``"navigator_"``).
            cleanup_on_exit: Register atexit cleanup (default True).
            cleanup_on_delete: Clean on __del__ (default True).
        """
        self.prefix = prefix
        self.cleanup_on_delete = cleanup_on_delete
        self.logger = logging.getLogger("navigator.storage.Temp")

        self._temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        self.logger.info("TempFileManager directory: %s", self._temp_dir)

        if cleanup_on_exit:
            atexit.register(self.cleanup)

    # ------------------------------------------------------------------ #
    # Cleanup                                                              #
    # ------------------------------------------------------------------ #

    def cleanup(self) -> None:
        """Remove the temp directory and all its contents.

        Errors are suppressed to avoid issues during interpreter shutdown.
        """
        with contextlib.suppress(Exception):
            if self._temp_dir.exists():
                shutil.rmtree(str(self._temp_dir), ignore_errors=True)

    def __del__(self) -> None:
        """Clean up on garbage collection if configured."""
        if self.cleanup_on_delete:
            self.cleanup()

    async def __aenter__(self) -> "TempFileManager":
        """Async context manager entry — returns self."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit — cleans up the temp directory."""
        self.cleanup()

    # ------------------------------------------------------------------ #
    # Backward-compat static methods (preserved from old TempFileManager) #
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_temp_file(suffix: str = "", prefix: str = "tmp", dir=None) -> str:
        """Create a temporary file and return its path.

        Args:
            suffix: File suffix.
            prefix: File prefix.
            dir: Directory to create the file in (defaults to system temp).

        Returns:
            Absolute path string to the new temp file.
        """
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
        os.close(fd)
        return path

    @staticmethod
    def remove_temp_file(file_path: str) -> None:
        """Remove a temp file by path.

        Args:
            file_path: Absolute path to the file to remove.
        """
        with contextlib.suppress(FileNotFoundError, OSError):
            if os.path.exists(file_path):
                os.remove(file_path)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_path(self, path: str) -> Path:
        """Resolve path within the temp directory, enforcing sandbox.

        Args:
            path: Relative path within the temp directory.

        Returns:
            Absolute resolved Path.

        Raises:
            ValueError: If the resolved path escapes the temp directory.
        """
        stripped = path.lstrip("/")
        candidate = (self._temp_dir / stripped).resolve()
        try:
            candidate.relative_to(self._temp_dir.resolve())
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {path!r} escapes the temp directory."
            )
        return candidate

    def _get_file_metadata(self, resolved: Path) -> FileMetadata:
        """Build a FileMetadata object for a resolved path.

        Args:
            resolved: Absolute path to an existing file.

        Returns:
            FileMetadata instance.
        """
        stat = resolved.stat()
        content_type, _ = mimetypes.guess_type(resolved.name)
        rel_path = str(resolved.relative_to(self._temp_dir))
        return FileMetadata(
            name=resolved.name,
            path=rel_path,
            size=stat.st_size,
            content_type=content_type,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            url=resolved.as_uri(),
        )

    # ------------------------------------------------------------------ #
    # Abstract method implementations                                     #
    # ------------------------------------------------------------------ #

    async def list_files(
        self, path: str = "", pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files in the temp directory.

        Args:
            path: Sub-directory relative to the temp root (default: root).
            pattern: Glob pattern applied to filenames (default ``"*"``).

        Returns:
            List of FileMetadata for matching files.
        """

        def _list() -> List[FileMetadata]:
            target = self._resolve_path(path) if path else self._temp_dir.resolve()
            results: List[FileMetadata] = []
            for entry in target.iterdir():
                if not entry.is_file():
                    continue
                if not fnmatch.fnmatch(entry.name, pattern):
                    continue
                results.append(self._get_file_metadata(entry))
            return results

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a file:// URI for a temp file.

        Args:
            path: Relative path within temp directory.
            expiry: Ignored (present for interface compat).

        Returns:
            ``file://`` URI string.
        """

        def _url() -> str:
            return self._resolve_path(path).as_uri()

        return await asyncio.to_thread(_url)

    async def upload_file(
        self, source: Union[BinaryIO, Path], destination: str
    ) -> FileMetadata:
        """Store a file in the temp directory.

        Args:
            source: Local Path or open binary stream to read from.
            destination: Target path relative to the temp directory.

        Returns:
            FileMetadata for the stored file.
        """

        def _upload() -> FileMetadata:
            dest = self._resolve_path(destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copy2(str(source), str(dest))
            else:
                with open(dest, "wb") as fout:
                    shutil.copyfileobj(source, fout)
            return self._get_file_metadata(dest)

        return await asyncio.to_thread(_upload)

    async def download_file(
        self, source: str, destination: Union[Path, BinaryIO]
    ) -> Path:
        """Move a temp file to the destination (move semantics).

        Moving out of the temp directory is intentional — once the caller
        "downloads" a file it is no longer managed by the temp manager.

        Args:
            source: Relative source path inside the temp directory.
            destination: Target Path or open binary stream.

        Returns:
            Path where the file was written.
        """

        def _download() -> Path:
            src = self._resolve_path(source)
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(destination))
                return destination
            else:
                with open(src, "rb") as fin:
                    shutil.copyfileobj(fin, destination)
                src.unlink(missing_ok=True)
                return src

        return await asyncio.to_thread(_download)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy a file within the temp directory.

        If the destination falls outside the temp dir, the file is moved there
        (external move semantics).

        Args:
            source: Source relative path.
            destination: Destination relative path.

        Returns:
            FileMetadata for the resulting file.
        """

        def _copy() -> FileMetadata:
            src = self._resolve_path(source)
            try:
                dest = self._resolve_path(destination)
            except ValueError:
                # Destination is outside temp dir — external move
                dest = Path(destination)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                content_type, _ = mimetypes.guess_type(dest.name)
                stat = dest.stat()
                return FileMetadata(
                    name=dest.name,
                    path=str(dest),
                    size=stat.st_size,
                    content_type=content_type,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    url=dest.as_uri(),
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            return self._get_file_metadata(dest)

        return await asyncio.to_thread(_copy)

    async def delete_file(self, path: str) -> bool:
        """Delete a file from the temp directory.

        Args:
            path: Relative file path to delete.

        Returns:
            True if deleted, False if not found.
        """

        def _delete() -> bool:
            try:
                target = self._resolve_path(path)
                if target.exists():
                    target.unlink()
                    return True
                return False
            except (FileNotFoundError, ValueError):
                return False

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        """Check whether a file exists in the temp directory.

        Args:
            path: Relative file path.

        Returns:
            True if the file exists and is a regular file.
        """

        def _exists() -> bool:
            try:
                target = self._resolve_path(path)
                return target.is_file()
            except (ValueError, OSError):
                return False

        return await asyncio.to_thread(_exists)

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Return metadata for a single file in the temp directory.

        Args:
            path: Relative file path.

        Returns:
            FileMetadata for the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """

        def _meta() -> FileMetadata:
            target = self._resolve_path(path)
            if not target.exists():
                raise FileNotFoundError(f"Temp file not found: {path!r}")
            return self._get_file_metadata(target)

        return await asyncio.to_thread(_meta)

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create or overwrite a file in the temp directory with raw bytes.

        Args:
            path: Relative file path.
            content: Raw bytes to write.

        Returns:
            True on success.
        """

        def _create() -> bool:
            target = self._resolve_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fout:
                fout.write(content)
            return True

        return await asyncio.to_thread(_create)
