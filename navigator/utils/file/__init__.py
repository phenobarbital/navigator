"""
navigator.utils.file — Unified File Manager Package.

Public API:
    FileManagerInterface  — Abstract base class for all file managers.
    FileMetadata          — Dataclass returned by all file operations.
    LocalFileManager      — Local disk operations (sandboxed, async).
    TempFileManager       — Temp files with auto-cleanup.
    S3FileManager         — AWS S3 (lazy-loaded on first access).
    GCSFileManager        — Google Cloud Storage (lazy-loaded on first access).
    FileServingExtension  — aiohttp web-serving layer (Range requests).
    FileManagerFactory    — Runtime creation by type string.

Backward compatibility:
    All existing imports from navigator.utils.file continue to work:
    ``from navigator.utils.file import GCSFileManager, S3FileManager, TempFileManager``

Lazy loading:
    S3FileManager and GCSFileManager are NOT imported at module load time.
    They are only loaded when accessed (via __getattr__) or imported
    explicitly.  This avoids pulling heavy cloud SDKs into memory until
    they are actually needed.
"""
from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

# ── Eagerly-loaded (no heavy cloud dependencies) ──────────────────────────
from .abstract import FileManagerInterface, FileMetadata
from .factory import FileManagerFactory
from .local import LocalFileManager
from .tmp import TempFileManager
from .web import FileServingExtension

# ── Lazy-load mapping: name → (relative module, class name) ───────────────
_LAZY: dict[str, tuple[str, str]] = {
    "S3FileManager": (".s3", "S3FileManager"),
    "GCSFileManager": (".gcs", "GCSFileManager"),
}

__all__ = [
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "TempFileManager",
    "S3FileManager",
    "GCSFileManager",
    "FileServingExtension",
    "FileManagerFactory",
]


def __getattr__(name: str):
    """Lazy-load cloud managers on first access.

    Args:
        name: Attribute name being accessed.

    Returns:
        The requested class.

    Raises:
        AttributeError: If the name is not a recognised lazy export.
    """
    if name in _LAZY:
        module_rel, class_name = _LAZY[name]
        module = importlib.import_module(module_rel, package=__package__)
        cls = getattr(module, class_name)
        # Cache in this module so subsequent access is instant
        setattr(sys.modules[__name__], name, cls)
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
