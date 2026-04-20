"""Tests for FileManagerFactory."""
import pytest
from unittest.mock import patch, MagicMock

from navigator.utils.file.factory import FileManagerFactory
from navigator.utils.file.local import LocalFileManager
from navigator.utils.file.tmp import TempFileManager
from navigator.utils.file.abstract import FileManagerInterface
import navigator.utils.file.s3 as _s3_module


class TestFileManagerFactory:
    def test_factory_create_local(self, tmp_path):
        """Factory creates LocalFileManager."""
        mgr = FileManagerFactory.create("local", base_path=tmp_path)
        assert isinstance(mgr, LocalFileManager)
        assert isinstance(mgr, FileManagerInterface)

    def test_factory_create_temp(self):
        """Factory creates TempFileManager."""
        mgr = FileManagerFactory.create("temp", cleanup_on_exit=False, cleanup_on_delete=False)
        assert isinstance(mgr, TempFileManager)
        assert isinstance(mgr, FileManagerInterface)
        mgr.cleanup()

    def test_factory_unknown_type(self):
        """Raises ValueError for unknown type."""
        with pytest.raises(ValueError, match="Unknown file manager type"):
            FileManagerFactory.create("unknown")

    def test_factory_create_s3_lazy(self):
        """Factory creates S3FileManager (lazy-imported)."""
        mock_creds = {
            "default": {
                "aws_key": "AKIATEST",
                "aws_secret": "secret",
                "region_name": "us-east-1",
                "bucket_name": "test-bucket",
            }
        }
        with patch.object(_s3_module, "AWS_CREDENTIALS", mock_creds):
            from navigator.utils.file.s3 import S3FileManager
            mgr = FileManagerFactory.create("s3", bucket_name="test-bucket",
                                             credentials=mock_creds["default"])
            assert isinstance(mgr, S3FileManager)
            assert isinstance(mgr, FileManagerInterface)

    def test_factory_create_gcs_lazy(self):
        """Factory creates GCSFileManager (lazy-imported)."""
        mock_creds = MagicMock()
        with patch("navigator.utils.file.gcs.google.auth.default", return_value=(mock_creds, "proj")):
            with patch("navigator.utils.file.gcs.storage.Client"):
                from navigator.utils.file.gcs import GCSFileManager
                mgr = FileManagerFactory.create("gcs", bucket_name="test-bucket")
                assert isinstance(mgr, GCSFileManager)
                assert isinstance(mgr, FileManagerInterface)

    def test_factory_error_message_lists_valid_types(self):
        """Error message lists all supported types."""
        with pytest.raises(ValueError) as exc_info:
            FileManagerFactory.create("invalid")
        msg = str(exc_info.value)
        assert "local" in msg
        assert "temp" in msg
        assert "s3" in msg
        assert "gcs" in msg
