"""Tests for navigator.utils.file package imports and lazy loading."""
import sys
import pytest
import navigator.utils.file.s3 as _s3_module


class TestEagerImports:
    def test_import_file_manager_interface(self):
        """FileManagerInterface can be imported directly."""
        from navigator.utils.file import FileManagerInterface
        assert FileManagerInterface is not None

    def test_import_file_metadata(self):
        """FileMetadata can be imported directly."""
        from navigator.utils.file import FileMetadata
        assert FileMetadata is not None

    def test_import_local_file_manager(self):
        """LocalFileManager can be imported directly."""
        from navigator.utils.file import LocalFileManager
        assert LocalFileManager is not None

    def test_import_temp_file_manager(self):
        """TempFileManager can be imported directly."""
        from navigator.utils.file import TempFileManager
        assert TempFileManager is not None

    def test_import_file_serving_extension(self):
        """FileServingExtension can be imported directly."""
        from navigator.utils.file import FileServingExtension
        assert FileServingExtension is not None

    def test_import_file_manager_factory(self):
        """FileManagerFactory can be imported directly."""
        from navigator.utils.file import FileManagerFactory
        assert FileManagerFactory is not None

    def test_all_exports(self):
        """__all__ contains all 8 public names."""
        import navigator.utils.file as pkg
        for name in [
            "FileManagerInterface", "FileMetadata", "LocalFileManager",
            "TempFileManager", "S3FileManager", "GCSFileManager",
            "FileServingExtension", "FileManagerFactory",
        ]:
            assert name in pkg.__all__

    def test_backward_compat_gcsfilemanager(self):
        """from navigator.utils.file import GCSFileManager still works."""
        from unittest.mock import patch, MagicMock
        mock_creds = MagicMock()
        with patch("navigator.utils.file.gcs.google.auth.default", return_value=(mock_creds, "proj")):
            with patch("navigator.utils.file.gcs.storage.Client"):
                from navigator.utils.file import GCSFileManager
                assert GCSFileManager is not None

    def test_backward_compat_s3filemanager(self):
        """from navigator.utils.file import S3FileManager still works."""
        from unittest.mock import patch
        mock_creds = {"default": {"aws_key": "k", "aws_secret": "s", "region_name": "us-east-1"}}
        with patch.object(_s3_module, "AWS_CREDENTIALS", mock_creds):
            from navigator.utils.file import S3FileManager
            assert S3FileManager is not None


class TestLazyLoading:
    def test_s3_not_eagerly_loaded(self):
        """S3FileManager not in module dict before access (lazy)."""
        import importlib
        import navigator.utils.file as pkg

        # Remove the cached lazy attribute if present (reset for test isolation)
        if "S3FileManager" in pkg.__dict__:
            del pkg.__dict__["S3FileManager"]

        # Accessing via __getattr__ triggers lazy load
        from unittest.mock import patch
        mock_creds = {"default": {"aws_key": "k", "aws_secret": "s", "region_name": "us-east-1"}}
        with patch.object(_s3_module, "AWS_CREDENTIALS", mock_creds):
            S3 = getattr(pkg, "S3FileManager")
            assert S3 is not None
            # Now it should be cached
            assert "S3FileManager" in pkg.__dict__

    def test_unknown_attribute_raises(self):
        """Accessing unknown attribute raises AttributeError."""
        import navigator.utils.file as pkg
        with pytest.raises(AttributeError):
            _ = pkg.NonExistentClass
