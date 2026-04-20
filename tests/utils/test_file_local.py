"""Tests for LocalFileManager."""
import pytest
from pathlib import Path

from navigator.utils.file.local import LocalFileManager
from navigator.utils.file.abstract import FileMetadata


@pytest.fixture
def tmp_dir(tmp_path):
    """Temporary directory with sample files for local manager tests."""
    (tmp_path / "test.txt").write_text("hello world")
    (tmp_path / "data.json").write_text('{"key": "value"}')
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested")
    return tmp_path


@pytest.fixture
def local_manager(tmp_dir):
    """LocalFileManager sandboxed to tmp_dir."""
    return LocalFileManager(base_path=tmp_dir, sandboxed=True)


class TestLocalList:
    @pytest.mark.asyncio
    async def test_local_list_files(self, local_manager):
        """list_files returns FileMetadata for all files in root."""
        files = await local_manager.list_files()
        names = [f.name for f in files]
        assert "test.txt" in names
        assert "data.json" in names

    @pytest.mark.asyncio
    async def test_local_list_files_with_pattern(self, local_manager):
        """list_files filters by glob pattern."""
        files = await local_manager.list_files(pattern="*.txt")
        names = [f.name for f in files]
        assert "test.txt" in names
        assert "data.json" not in names

    @pytest.mark.asyncio
    async def test_local_list_files_returns_metadata(self, local_manager):
        """list_files returns proper FileMetadata objects."""
        files = await local_manager.list_files()
        for f in files:
            assert isinstance(f, FileMetadata)
            assert f.name
            assert f.size >= 0
            assert f.url.startswith("file://")


class TestLocalCRUD:
    @pytest.mark.asyncio
    async def test_local_upload_download(self, local_manager, tmp_path):
        """Upload file, verify metadata, download and compare."""
        source = tmp_path / "source.txt"
        source.write_bytes(b"upload content")

        meta = await local_manager.upload_file(source, "uploaded.txt")
        assert meta.name == "uploaded.txt"
        assert meta.size == len(b"upload content")

        download_path = tmp_path / "downloaded.txt"
        result = await local_manager.download_file("uploaded.txt", download_path)
        assert download_path.read_bytes() == b"upload content"

    @pytest.mark.asyncio
    async def test_local_copy_delete(self, local_manager):
        """Copy file, verify exists, delete, verify gone."""
        meta = await local_manager.copy_file("test.txt", "test_copy.txt")
        assert meta.name == "test_copy.txt"
        assert await local_manager.exists("test_copy.txt")

        deleted = await local_manager.delete_file("test_copy.txt")
        assert deleted is True
        assert not await local_manager.exists("test_copy.txt")

    @pytest.mark.asyncio
    async def test_local_create_from_text(self, local_manager):
        """Create text file, read back, verify encoding."""
        result = await local_manager.create_from_text("hello.txt", "hello world")
        assert result is True

        meta = await local_manager.get_file_metadata("hello.txt")
        assert meta.size == len("hello world".encode("utf-8"))

    @pytest.mark.asyncio
    async def test_local_create_from_bytes(self, local_manager):
        """Create binary file from BytesIO."""
        from io import BytesIO
        buf = BytesIO(b"\x00\x01\x02\x03")
        result = await local_manager.create_from_bytes("binary.bin", buf)
        assert result is True
        assert await local_manager.exists("binary.bin")

    @pytest.mark.asyncio
    async def test_local_exists(self, local_manager):
        """exists() returns True/False correctly."""
        assert await local_manager.exists("test.txt")
        assert not await local_manager.exists("nonexistent.xyz")

    @pytest.mark.asyncio
    async def test_local_get_file_metadata(self, local_manager):
        """Metadata fields populated correctly."""
        meta = await local_manager.get_file_metadata("test.txt")
        assert meta.name == "test.txt"
        assert meta.size == len("hello world")
        assert meta.content_type == "text/plain"
        assert meta.modified_at is not None
        assert meta.url.startswith("file://")

    @pytest.mark.asyncio
    async def test_local_get_file_metadata_not_found(self, local_manager):
        """get_file_metadata raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            await local_manager.get_file_metadata("does_not_exist.txt")


class TestLocalSandboxing:
    @pytest.mark.asyncio
    async def test_local_sandboxing_blocks_traversal(self, local_manager):
        """Path traversal (../) raises ValueError."""
        with pytest.raises(ValueError, match="traversal"):
            await local_manager.get_file_metadata("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_local_exists_traversal_returns_false(self, local_manager):
        """exists() returns False (not raises) for traversal paths."""
        result = await local_manager.exists("../../etc/passwd")
        assert result is False

    @pytest.mark.asyncio
    async def test_local_symlink_blocked(self, tmp_dir):
        """Symlink access denied when follow_symlinks=False."""
        target = tmp_dir / "real.txt"
        target.write_text("real content")
        link = tmp_dir / "link.txt"
        link.symlink_to(target)

        manager = LocalFileManager(
            base_path=tmp_dir, follow_symlinks=False, sandboxed=True
        )
        files = await manager.list_files()
        names = [f.name for f in files]
        assert "link.txt" not in names  # symlinks are skipped in listing

    @pytest.mark.asyncio
    async def test_local_no_sandbox(self, tmp_dir):
        """Sandboxing=False allows path resolution without traversal check."""
        manager = LocalFileManager(base_path=tmp_dir, sandboxed=False)
        # With sandboxing off, resolving existing paths should work fine
        assert await manager.exists("test.txt")


class TestLocalFindFiles:
    @pytest.mark.asyncio
    async def test_local_find_files_by_extension(self, local_manager):
        """find_files() filters by extension recursively."""
        results = await local_manager.find_files(extension=".txt")
        names = [f.name for f in results]
        assert "test.txt" in names
        assert "nested.txt" in names
        assert "data.json" not in names

    @pytest.mark.asyncio
    async def test_local_find_files_by_keyword(self, local_manager):
        """find_files() filters by keyword."""
        results = await local_manager.find_files(keywords="test")
        names = [f.name for f in results]
        assert "test.txt" in names

    @pytest.mark.asyncio
    async def test_local_get_url(self, local_manager):
        """get_file_url() returns file:// URI."""
        url = await local_manager.get_file_url("test.txt")
        assert url.startswith("file://")
