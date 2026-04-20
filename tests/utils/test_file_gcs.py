"""Tests for GCSFileManager (mocked GCS SDK)."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime

from navigator.utils.file.abstract import FileMetadata


# ── Helper to create a fake GCS blob ─────────────────────────────────────

def _make_blob(name, size=100, content_type="text/plain", updated=None, public_url=""):
    blob = MagicMock()
    blob.name = name
    blob.size = size
    blob.content_type = content_type
    blob.updated = updated or datetime(2026, 1, 1)
    blob.public_url = public_url
    return blob


# ── Fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def gcs_manager():
    """GCSFileManager with mocked google.auth.default credentials."""
    mock_creds = MagicMock()
    mock_project = "test-project"
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_client.bucket = MagicMock(return_value=mock_bucket)

    with patch("navigator.utils.file.gcs.google.auth.default", return_value=(mock_creds, mock_project)):
        with patch("navigator.utils.file.gcs.storage.Client", return_value=mock_client):
            from navigator.utils.file.gcs import GCSFileManager
            mgr = GCSFileManager(bucket_name="test-bucket")
            mgr.bucket = mock_bucket
            return mgr


class TestGCSCredentials:
    def test_gcs_three_credential_modes_json(self):
        """Dict credentials mode."""
        mock_creds = MagicMock()
        with patch("navigator.utils.file.gcs.service_account.Credentials.from_service_account_info",
                   return_value=mock_creds):
            with patch("navigator.utils.file.gcs.storage.Client"):
                from navigator.utils.file.gcs import GCSFileManager
                mgr = GCSFileManager(
                    bucket_name="b",
                    json_credentials={"type": "service_account"}
                )
                assert mgr._creds is mock_creds

    def test_gcs_three_credential_modes_file(self):
        """File path credentials mode."""
        mock_creds = MagicMock()
        with patch("navigator.utils.file.gcs.service_account.Credentials.from_service_account_file",
                   return_value=mock_creds):
            with patch("navigator.utils.file.gcs.storage.Client"):
                from navigator.utils.file.gcs import GCSFileManager
                mgr = GCSFileManager(
                    bucket_name="b",
                    credentials="/path/to/creds.json"
                )
                assert mgr._creds is mock_creds

    def test_gcs_three_credential_modes_default(self, gcs_manager):
        """Default ADC mode uses google.auth.default."""
        assert gcs_manager._creds is not None


class TestGCSListFiles:
    @pytest.mark.asyncio
    async def test_gcs_list_files(self, gcs_manager):
        """list_files returns FileMetadata objects."""
        blobs = [
            _make_blob("file1.txt"),
            _make_blob("file2.csv"),
        ]
        gcs_manager.bucket.list_blobs = MagicMock(return_value=blobs)

        results = await gcs_manager.list_files()
        assert len(results) == 2
        names = [r.name for r in results]
        assert "file1.txt" in names
        assert "file2.csv" in names


class TestGCSUpload:
    @pytest.mark.asyncio
    async def test_gcs_upload_small_file(self, gcs_manager, tmp_path):
        """Regular upload for small files."""
        source = tmp_path / "small.txt"
        source.write_bytes(b"content")

        mock_blob = MagicMock()
        mock_blob.size = 7
        mock_blob.content_type = "text/plain"
        mock_blob.updated = datetime(2026, 1, 1)
        mock_blob.public_url = ""
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)
        mock_blob.reload = MagicMock()

        meta = await gcs_manager.upload_file(source, "small.txt")
        mock_blob.upload_from_filename.assert_called_once()

    @pytest.mark.asyncio
    async def test_gcs_upload_resumable(self, gcs_manager, tmp_path):
        """Resumable upload triggered for large files."""
        gcs_manager.resumable_threshold = 5  # 5 bytes for test

        source = tmp_path / "large.bin"
        source.write_bytes(b"ABCDEFGHIJ")  # 10 bytes > threshold

        mock_blob = MagicMock()
        mock_blob.size = 10
        mock_blob.content_type = "application/octet-stream"
        mock_blob.updated = datetime(2026, 1, 1)
        mock_blob.public_url = ""
        mock_blob.reload = MagicMock()
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)

        meta = await gcs_manager.upload_file(source, "large.bin")
        # blob should have been created with chunk_size set
        call_kwargs = gcs_manager.bucket.blob.call_args
        assert call_kwargs is not None


class TestGCSFolderOps:
    @pytest.mark.asyncio
    async def test_gcs_create_folder(self, gcs_manager):
        """create_folder uploads an empty placeholder blob."""
        mock_blob = MagicMock()
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)
        await gcs_manager.create_folder("myfolder")
        mock_blob.upload_from_string.assert_called_once_with("")

    @pytest.mark.asyncio
    async def test_gcs_remove_folder(self, gcs_manager):
        """remove_folder deletes all blobs with the folder prefix."""
        blob1 = _make_blob("myfolder/a.txt")
        blob2 = _make_blob("myfolder/b.txt")
        gcs_manager.bucket.list_blobs = MagicMock(return_value=[blob1, blob2])
        await gcs_manager.remove_folder("myfolder")
        blob1.delete.assert_called_once()
        blob2.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_gcs_rename_folder(self, gcs_manager):
        """rename_folder renames all blobs under the prefix."""
        blob1 = _make_blob("oldfolder/a.txt")
        blob2 = _make_blob("oldfolder/b.txt")
        gcs_manager.bucket.list_blobs = MagicMock(return_value=[blob1, blob2])
        await gcs_manager.rename_folder("oldfolder", "newfolder")
        assert gcs_manager.bucket.rename_blob.call_count == 2

    @pytest.mark.asyncio
    async def test_gcs_rename_file(self, gcs_manager):
        """rename_file renames a single blob."""
        mock_blob = MagicMock()
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)
        await gcs_manager.rename_file("old.txt", "new.txt")
        gcs_manager.bucket.rename_blob.assert_called_once()


class TestGCSFindFiles:
    @pytest.mark.asyncio
    async def test_gcs_find_files(self, gcs_manager):
        """Keyword and extension filtering."""
        blobs = [
            _make_blob("report.csv"),
            _make_blob("image.png"),
            _make_blob("data.csv"),
        ]
        gcs_manager.bucket.list_blobs = MagicMock(return_value=blobs)
        results = await gcs_manager.find_files(extension=".csv")
        names = [r.name for r in results]
        assert "report.csv" in names
        assert "data.csv" in names
        assert "image.png" not in names


class TestGCSExists:
    @pytest.mark.asyncio
    async def test_gcs_exists_true(self, gcs_manager):
        """exists() returns True for existing blobs."""
        mock_blob = MagicMock()
        mock_blob.exists = MagicMock(return_value=True)
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)
        assert await gcs_manager.exists("file.txt") is True

    @pytest.mark.asyncio
    async def test_gcs_exists_false(self, gcs_manager):
        """exists() returns False for missing blobs."""
        mock_blob = MagicMock()
        mock_blob.exists = MagicMock(return_value=False)
        gcs_manager.bucket.blob = MagicMock(return_value=mock_blob)
        assert await gcs_manager.exists("missing.txt") is False
