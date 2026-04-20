"""
FileManagerInterface — Abstract Base Class for all file managers.

Defines the contract all file managers implement, including FileMetadata
dataclass for unified metadata returns across all operations.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO, List, Optional, Union


@dataclass
class FileMetadata:
    """Unified metadata returned by all file operations.

    Attributes:
        name: Filename only (no directory path).
        path: Relative or full path / cloud storage key.
        size: File size in bytes.
        content_type: MIME type of the file, if known.
        modified_at: Last modification timestamp, if known.
        url: Public or signed URL if available, else None.
    """

    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]


class FileManagerInterface(ABC):
    """Abstract base class defining the contract for all file managers.

    All concrete implementations (LocalFileManager, TempFileManager,
    S3FileManager, GCSFileManager) must implement the 9 abstract methods.
    Three concrete helper methods are provided by default.

    The ``find_files()`` method has a default implementation that calls
    ``list_files()`` and filters in-memory; managers may override it with
    a more efficient server-side implementation.
    """

    # ------------------------------------------------------------------ #
    # Abstract methods — must be implemented by every manager             #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def list_files(
        self, path: str = "", pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files at the given path, optionally filtered by pattern.

        Args:
            path: Directory path or key prefix to list.
            pattern: Glob-style pattern to filter filenames (default ``"*"``).

        Returns:
            List of FileMetadata objects for matching files.
        """

    @abstractmethod
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a URL for accessing the file.

        Args:
            path: File path or cloud storage key.
            expiry: Signed URL expiry in seconds (default 3600).

        Returns:
            URL string (``file://``, presigned, or app-served).
        """

    @abstractmethod
    async def upload_file(
        self, source: Union[BinaryIO, Path], destination: str
    ) -> FileMetadata:
        """Upload a file from a local path or file-like object.

        Args:
            source: Local Path or open binary file object.
            destination: Target path or cloud key.

        Returns:
            FileMetadata for the uploaded file.
        """

    @abstractmethod
    async def download_file(
        self, source: str, destination: Union[Path, BinaryIO]
    ) -> Path:
        """Download a file to a local path or file-like object.

        Args:
            source: Source path or cloud key.
            destination: Local Path or open binary file object to write to.

        Returns:
            Path to the downloaded file.
        """

    @abstractmethod
    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy a file within the same storage backend.

        Args:
            source: Source path or cloud key.
            destination: Destination path or cloud key.

        Returns:
            FileMetadata for the copied file.
        """

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file.

        Args:
            path: File path or cloud key to delete.

        Returns:
            True if deleted, False if the file did not exist.
        """

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check whether a file exists.

        Args:
            path: File path or cloud key.

        Returns:
            True if the file exists, False otherwise.
        """

    @abstractmethod
    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Retrieve metadata for a single file.

        Args:
            path: File path or cloud key.

        Returns:
            FileMetadata for the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """

    @abstractmethod
    async def create_file(self, path: str, content: bytes) -> bool:
        """Create or overwrite a file with raw bytes content.

        Args:
            path: Target file path or cloud key.
            content: Raw bytes to write.

        Returns:
            True on success.
        """

    # ------------------------------------------------------------------ #
    # GCS folder operations — abstract, default raises NotImplementedError #
    # ------------------------------------------------------------------ #

    async def create_folder(self, folder_name: str) -> None:
        """Create a "folder" in the storage backend (GCS-style placeholder).

        Args:
            folder_name: Name of the folder to create.

        Raises:
            NotImplementedError: If the backend does not support folders.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support create_folder()."
        )

    async def remove_folder(self, folder_name: str) -> None:
        """Remove a "folder" and all its contents.

        Args:
            folder_name: Name of the folder to remove.

        Raises:
            NotImplementedError: If the backend does not support folders.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support remove_folder()."
        )

    async def rename_folder(
        self, old_folder_name: str, new_folder_name: str
    ) -> None:
        """Rename a "folder" in the storage backend.

        Args:
            old_folder_name: Current folder name.
            new_folder_name: New folder name.

        Raises:
            NotImplementedError: If the backend does not support folders.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support rename_folder()."
        )

    async def rename_file(self, old_file_name: str, new_file_name: str) -> None:
        """Rename a file in the storage backend.

        Args:
            old_file_name: Current file name / key.
            new_file_name: New file name / key.

        Raises:
            NotImplementedError: If the backend does not support rename.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support rename_file()."
        )

    # ------------------------------------------------------------------ #
    # Concrete helper methods                                              #
    # ------------------------------------------------------------------ #

    async def create_from_text(
        self, path: str, text: str, encoding: str = "utf-8"
    ) -> bool:
        """Create a file from a text string.

        Args:
            path: Target file path or cloud key.
            text: Text content to write.
            encoding: Character encoding (default ``"utf-8"``).

        Returns:
            True on success.
        """
        return await self.create_file(path, text.encode(encoding))

    async def create_from_bytes(
        self, path: str, data: Union[bytes, BytesIO, StringIO]
    ) -> bool:
        """Create a file from bytes, BytesIO, or StringIO.

        Args:
            path: Target file path or cloud key.
            data: Content as raw bytes, BytesIO, or StringIO object.

        Returns:
            True on success.
        """
        if isinstance(data, StringIO):
            raw = data.getvalue().encode("utf-8")
        elif isinstance(data, BytesIO):
            raw = data.getvalue()
        else:
            raw = data
        return await self.create_file(path, raw)

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """Find files by keyword(s), extension, and/or prefix.

        Default implementation calls ``list_files()`` and filters in-memory.
        Concrete managers may override for a more efficient server-side search.

        Args:
            keywords: One or more substrings that must appear in the filename.
            extension: File extension to filter by (e.g. ``".csv"``).
            prefix: Path/key prefix to restrict the search scope.

        Returns:
            List of matching FileMetadata objects.
        """
        files = await self.list_files(path=prefix or "")
        results: List[FileMetadata] = []
        for f in files:
            if extension and not f.name.endswith(extension):
                continue
            if keywords:
                kw_list: List[str] = (
                    [keywords] if isinstance(keywords, str) else list(keywords)
                )
                if not all(kw in f.name for kw in kw_list):
                    continue
            results.append(f)
        return results
