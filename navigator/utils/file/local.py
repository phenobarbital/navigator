"""
LocalFileManager.

Local disk file manager with sandboxing (path traversal protection),
symlink control, and async-first I/O via asyncio.to_thread().
"""
import asyncio
import fnmatch
import mimetypes
import os
import shutil
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO, List, Optional, Union

from navconfig.logging import logging

from .abstract import FileManagerInterface, FileMetadata


class LocalFileManager(FileManagerInterface):
    """Local filesystem file manager.

    All blocking I/O operations are executed via ``asyncio.to_thread()``
    so they do not block the event loop.

    Sandboxing is enabled by default: any path that resolves outside
    ``base_path`` raises ``ValueError``.  Symlink traversal can be
    controlled via ``follow_symlinks``.

    Attributes:
        manager_name: Identifier used in app context registration.
        base_path: Root directory for all operations.
        sandboxed: Whether to enforce sandbox restrictions.
        follow_symlinks: Whether symlinks are allowed.
    """

    manager_name: str = "localfile"

    def __init__(
        self,
        base_path: Optional[Union[str, Path]] = None,
        create_base: bool = True,
        follow_symlinks: bool = False,
        sandboxed: bool = True,
    ) -> None:
        """Initialize the LocalFileManager.

        Args:
            base_path: Root directory. Defaults to current working directory.
            create_base: If True, create base_path if it does not exist.
            follow_symlinks: If False (default), symlinks are rejected.
            sandboxed: If True (default), block path traversal outside base.
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.follow_symlinks = follow_symlinks
        self.sandboxed = sandboxed
        self.logger = logging.getLogger("navigator.storage.Local")

        if create_base and not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "LocalFileManager initialised at %s (sandboxed=%s)",
            self.base_path,
            self.sandboxed,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path against base_path, enforcing the sandbox.

        Args:
            path: Relative file path within the sandbox.

        Returns:
            Absolute resolved Path.

        Raises:
            ValueError: If the resolved path escapes the sandbox or if
                        the path points to a symlink and follow_symlinks
                        is False.
        """
        # Strip leading slashes so Path joining works correctly
        stripped = path.lstrip("/")
        candidate = (self.base_path / stripped).resolve()

        if not self.follow_symlinks and candidate.is_symlink():
            raise ValueError(
                f"Symlink traversal blocked: {path!r} resolves to a symlink."
            )

        if self.sandboxed:
            try:
                candidate.relative_to(self.base_path.resolve())
            except ValueError:
                raise ValueError(
                    f"Path traversal detected: {path!r} escapes the sandbox."
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
        rel_path = str(resolved.relative_to(self.base_path))
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
        """List files in a directory, optionally filtered by glob pattern.

        Args:
            path: Sub-directory relative to base_path (default: root).
            pattern: Glob pattern applied to filenames (default ``"*"``).

        Returns:
            List of FileMetadata for matching files (non-recursive).
        """

        def _list() -> List[FileMetadata]:
            target = self._resolve_path(path) if path else self.base_path.resolve()
            results: List[FileMetadata] = []
            for entry in target.iterdir():
                if entry.is_symlink() and not self.follow_symlinks:
                    continue
                if not entry.is_file():
                    continue
                if not fnmatch.fnmatch(entry.name, pattern):
                    continue
                results.append(self._get_file_metadata(entry))
            return results

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a file:// URI for the resolved path.

        Args:
            path: Relative file path.
            expiry: Ignored for local files (present for interface compat).

        Returns:
            ``file://`` URI string.
        """

        def _url() -> str:
            return self._resolve_path(path).as_uri()

        return await asyncio.to_thread(_url)

    async def upload_file(
        self, source: Union[BinaryIO, Path], destination: str
    ) -> FileMetadata:
        """Copy a file from source into the sandbox at destination.

        Args:
            source: Local Path or open binary stream to read from.
            destination: Target path relative to base_path.

        Returns:
            FileMetadata for the written file.
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
        """Copy a file from the sandbox to a destination path or stream.

        Args:
            source: Relative source path inside the sandbox.
            destination: Target Path or open binary stream.

        Returns:
            Path where the file was written (or source resolved path if stream).
        """

        def _download() -> Path:
            src = self._resolve_path(source)
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(destination))
                return destination
            else:
                with open(src, "rb") as fin:
                    shutil.copyfileobj(fin, destination)
                return src

        return await asyncio.to_thread(_download)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy a file within the sandbox.

        Args:
            source: Source relative path.
            destination: Destination relative path.

        Returns:
            FileMetadata for the copied file.
        """

        def _copy() -> FileMetadata:
            src = self._resolve_path(source)
            dest = self._resolve_path(destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            return self._get_file_metadata(dest)

        return await asyncio.to_thread(_copy)

    async def delete_file(self, path: str) -> bool:
        """Delete a file from the sandbox.

        Args:
            path: Relative file path to delete.

        Returns:
            True if deleted, False if the file did not exist.
        """

        def _delete() -> bool:
            try:
                target = self._resolve_path(path)
                if target.exists():
                    target.unlink()
                    return True
                return False
            except FileNotFoundError:
                return False

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        """Check whether a file exists in the sandbox.

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
        """Return metadata for a single file in the sandbox.

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
                raise FileNotFoundError(f"File not found: {path!r}")
            return self._get_file_metadata(target)

        return await asyncio.to_thread(_meta)

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create or overwrite a file with raw bytes.

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

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """Find files by keyword(s) and/or extension (recursive search).

        Args:
            keywords: Substring(s) that must appear in the filename.
            extension: File extension to filter by (e.g. ``".txt"``).
            prefix: Sub-directory to restrict the search scope.

        Returns:
            List of matching FileMetadata objects.
        """

        def _find() -> List[FileMetadata]:
            root = (
                self._resolve_path(prefix)
                if prefix
                else self.base_path.resolve()
            )
            results: List[FileMetadata] = []
            for entry in root.rglob("*"):
                if entry.is_symlink() and not self.follow_symlinks:
                    continue
                if not entry.is_file():
                    continue
                name = entry.name
                if extension and not name.endswith(extension):
                    continue
                if keywords:
                    kw_list: List[str] = (
                        [keywords] if isinstance(keywords, str) else list(keywords)
                    )
                    if not all(kw in name for kw in kw_list):
                        continue
                results.append(self._get_file_metadata(entry))
            return results

        return await asyncio.to_thread(_find)
