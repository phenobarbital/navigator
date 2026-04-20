"""
FileManagerFactory.

Runtime creation of file managers by type string.
Cloud managers (S3, GCS) are lazily imported via importlib to avoid
importing heavy cloud SDKs at module load time.
"""
import importlib
from typing import Any

from .abstract import FileManagerInterface


class FileManagerFactory:
    """Factory for creating FileManagerInterface instances by type string.

    Supported type strings:
    - ``"local"`` — LocalFileManager (local disk)
    - ``"temp"`` — TempFileManager (temporary files with auto-cleanup)
    - ``"s3"`` — S3FileManager (AWS S3, lazy-imported)
    - ``"gcs"`` — GCSFileManager (Google Cloud Storage, lazy-imported)

    Example::

        manager = FileManagerFactory.create("local", base_path="/tmp/files")
        s3 = FileManagerFactory.create("s3", bucket_name="my-bucket")
    """

    # Eager-loaded manager types (no heavy dependencies)
    _EAGER_MANAGERS = {
        "local": (".local", "LocalFileManager"),
        "temp": (".tmp", "TempFileManager"),
    }

    # Lazy-loaded manager types (cloud SDKs — only imported on demand)
    _LAZY_MANAGERS = {
        "s3": (".s3", "S3FileManager"),
        "gcs": (".gcs", "GCSFileManager"),
    }

    @staticmethod
    def create(manager_type: str, **kwargs: Any) -> FileManagerInterface:
        """Create and return a file manager instance.

        Args:
            manager_type: Type string identifying the manager.
                          One of ``"local"``, ``"temp"``, ``"s3"``, ``"gcs"``.
            **kwargs: Constructor arguments forwarded to the manager class.

        Returns:
            A configured FileManagerInterface instance.

        Raises:
            ValueError: If ``manager_type`` is not recognised.
        """
        all_managers = {
            **FileManagerFactory._EAGER_MANAGERS,
            **FileManagerFactory._LAZY_MANAGERS,
        }

        if manager_type not in all_managers:
            supported = ", ".join(f'"{t}"' for t in sorted(all_managers))
            raise ValueError(
                f"Unknown file manager type: {manager_type!r}. "
                f"Supported types: {supported}."
            )

        module_rel, class_name = all_managers[manager_type]

        # importlib resolves relative to this package
        module = importlib.import_module(module_rel, package=__package__)
        cls = getattr(module, class_name)
        return cls(**kwargs)
