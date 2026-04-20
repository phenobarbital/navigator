"""Tests for S3FileManager (mocked aioboto3)."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from io import BytesIO

from navigator.utils.file.abstract import FileMetadata
# Import s3 module explicitly to allow patching
import navigator.utils.file.s3 as _s3_module


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def mock_s3_credentials():
    """Mock AWS credentials dict."""
    return {
        "default": {
            "aws_key": "AKIAEXAMPLE",
            "aws_secret": "secret",
            "region_name": "us-east-1",
            "bucket_name": "test-bucket",
        }
    }


@pytest.fixture
def s3_manager(mock_s3_credentials):
    """S3FileManager with mocked credentials."""
    with patch.object(_s3_module, "AWS_CREDENTIALS", mock_s3_credentials):
        from navigator.utils.file.s3 import S3FileManager
        mgr = S3FileManager(bucket_name="test-bucket")
        return mgr


# ── Helper: mock the S3 client context manager ────────────────────────────

def _make_s3_ctx(mock_client):
    """Return an async context manager that yields mock_client."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestS3Credentials:
    def test_s3_credentials_from_constructor(self, mock_s3_credentials):
        """Constructor params override navigator.conf."""
        with patch.object(_s3_module, "AWS_CREDENTIALS", mock_s3_credentials):
            from navigator.utils.file.s3 import S3FileManager
            creds = {
                "aws_key": "CUSTOM_KEY",
                "aws_secret": "CUSTOM_SECRET",
                "region_name": "eu-west-1",
            }
            mgr = S3FileManager(
                bucket_name="custom-bucket", credentials=creds
            )
            assert mgr.aws_config["aws_access_key_id"] == "CUSTOM_KEY"
            assert mgr.aws_config["region_name"] == "eu-west-1"

    def test_s3_credentials_from_conf(self, mock_s3_credentials):
        """Falls back to AWS_CREDENTIALS."""
        with patch.object(_s3_module, "AWS_CREDENTIALS", mock_s3_credentials):
            from navigator.utils.file.s3 import S3FileManager
            mgr = S3FileManager()
            assert mgr.aws_config["aws_access_key_id"] == "AKIAEXAMPLE"
            assert mgr.bucket_name == "test-bucket"

    def test_s3_missing_credentials_raises(self, mock_s3_credentials):
        """Missing credentials raises ValueError."""
        with patch.object(_s3_module, "AWS_CREDENTIALS", {}):
            from navigator.utils.file.s3 import S3FileManager
            with pytest.raises(ValueError, match="credentials"):
                S3FileManager()


class TestS3ListFiles:
    @pytest.mark.asyncio
    async def test_s3_list_files_paginated(self, s3_manager):
        """Paginated listing returns FileMetadata objects."""
        mock_client = MagicMock()
        paginator = MagicMock()
        paginator.paginate = MagicMock(
            return_value=self._async_iter([
                {"Contents": [
                    {"Key": "file1.txt", "Size": 100, "LastModified": None},
                    {"Key": "file2.csv", "Size": 200, "LastModified": None},
                ]}
            ])
        )
        mock_client.get_paginator = MagicMock(return_value=paginator)

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            results = await s3_manager.list_files()

        assert len(results) == 2
        names = [r.name for r in results]
        assert "file1.txt" in names
        assert "file2.csv" in names
        for r in results:
            assert isinstance(r, FileMetadata)

    @staticmethod
    async def _async_iter(items):
        for item in items:
            yield item


class TestS3Upload:
    @pytest.mark.asyncio
    async def test_s3_upload_small_file(self, s3_manager, tmp_path):
        """Regular upload for files below threshold."""
        source = tmp_path / "small.txt"
        source.write_bytes(b"small content")

        mock_client = MagicMock()
        mock_client.upload_file = AsyncMock()
        mock_client.head_object = AsyncMock(return_value={
            "ContentLength": 13,
            "LastModified": None,
        })

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            meta = await s3_manager.upload_file(source, "small.txt")

        mock_client.upload_file.assert_called_once()
        assert meta.name == "small.txt"

    @pytest.mark.asyncio
    async def test_s3_upload_multipart(self, s3_manager, tmp_path):
        """Multipart upload triggered for large files (threshold lowered for test)."""
        s3_manager.multipart_threshold = 5  # 5 bytes for testing

        source = tmp_path / "large.bin"
        source.write_bytes(b"ABCDEFGHIJ")  # 10 bytes > threshold

        mock_client = MagicMock()
        mock_client.create_multipart_upload = AsyncMock(
            return_value={"UploadId": "upload-123"}
        )
        mock_client.upload_part = AsyncMock(return_value={"ETag": '"etag1"'})
        mock_client.complete_multipart_upload = AsyncMock()

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            await s3_manager._multipart_upload_path(source, "large.bin", "application/octet-stream")

        mock_client.create_multipart_upload.assert_called_once()
        mock_client.complete_multipart_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_s3_multipart_abort_on_failure(self, s3_manager, tmp_path):
        """Failed multipart upload is aborted."""
        s3_manager.multipart_threshold = 5

        source = tmp_path / "fail.bin"
        source.write_bytes(b"ABCDEFGHIJ")

        mock_client = MagicMock()
        mock_client.create_multipart_upload = AsyncMock(
            return_value={"UploadId": "upload-fail"}
        )
        mock_client.upload_part = AsyncMock(side_effect=RuntimeError("Upload failed"))
        mock_client.abort_multipart_upload = AsyncMock()

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            with pytest.raises(RuntimeError):
                await s3_manager._multipart_upload_path(
                    source, "fail.bin", "application/octet-stream"
                )

        mock_client.abort_multipart_upload.assert_called_once()


class TestS3PresignedUrl:
    @pytest.mark.asyncio
    async def test_s3_presigned_url(self, s3_manager):
        """Presigned URL generation."""
        mock_client = MagicMock()
        mock_client.generate_presigned_url = AsyncMock(
            return_value="https://s3.amazonaws.com/test-bucket/file.txt?sig=xxx"
        )

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            url = await s3_manager.get_file_url("file.txt", expiry=3600)

        assert "s3.amazonaws.com" in url


class TestS3FindFiles:
    @pytest.mark.asyncio
    async def test_s3_find_files(self, s3_manager):
        """Keyword and extension filtering."""
        mock_client = MagicMock()
        paginator = MagicMock()
        paginator.paginate = MagicMock(
            return_value=TestS3ListFiles._async_iter([
                {"Contents": [
                    {"Key": "report_2026.csv", "Size": 100, "LastModified": None},
                    {"Key": "image.png", "Size": 500, "LastModified": None},
                    {"Key": "data.csv", "Size": 200, "LastModified": None},
                ]}
            ])
        )
        mock_client.get_paginator = MagicMock(return_value=paginator)

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            results = await s3_manager.find_files(extension=".csv")
        names = [r.name for r in results]
        assert "report_2026.csv" in names
        assert "data.csv" in names
        assert "image.png" not in names


class TestS3Exists:
    @pytest.mark.asyncio
    async def test_s3_exists_true(self, s3_manager):
        """exists() returns True for existing objects."""
        mock_client = MagicMock()
        mock_client.head_object = AsyncMock(return_value={})

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            result = await s3_manager.exists("file.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_s3_exists_false(self, s3_manager):
        """exists() returns False for missing objects."""
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        error = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject"
        )
        mock_client.head_object = AsyncMock(side_effect=error)

        with patch.object(s3_manager, "_s3_client", return_value=_make_s3_ctx(mock_client)):
            result = await s3_manager.exists("missing.txt")
        assert result is False
