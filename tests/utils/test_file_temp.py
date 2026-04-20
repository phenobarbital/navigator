"""Tests for TempFileManager."""
import pytest
from pathlib import Path

from navigator.utils.file.tmp import TempFileManager
from navigator.utils.file.abstract import FileMetadata


@pytest.fixture
def temp_manager():
    """TempFileManager with auto-cleanup."""
    return TempFileManager(prefix="test_nav_", cleanup_on_exit=False, cleanup_on_delete=False)


class TestTempBasicOps:
    @pytest.mark.asyncio
    async def test_temp_list_and_create(self, temp_manager):
        """Create files in temp, list them."""
        await temp_manager.create_file("hello.txt", b"hello")
        await temp_manager.create_file("world.txt", b"world")
        files = await temp_manager.list_files()
        names = [f.name for f in files]
        assert "hello.txt" in names
        assert "world.txt" in names

    @pytest.mark.asyncio
    async def test_temp_exists(self, temp_manager):
        """exists() works correctly."""
        assert not await temp_manager.exists("missing.txt")
        await temp_manager.create_file("present.txt", b"data")
        assert await temp_manager.exists("present.txt")

    @pytest.mark.asyncio
    async def test_temp_metadata(self, temp_manager):
        """get_file_metadata returns correct info."""
        await temp_manager.create_file("meta.txt", b"content")
        meta = await temp_manager.get_file_metadata("meta.txt")
        assert meta.name == "meta.txt"
        assert meta.size == len(b"content")
        assert meta.url.startswith("file://")

    @pytest.mark.asyncio
    async def test_temp_delete(self, temp_manager):
        """delete_file removes file."""
        await temp_manager.create_file("todel.txt", b"bye")
        assert await temp_manager.exists("todel.txt")
        deleted = await temp_manager.delete_file("todel.txt")
        assert deleted is True
        assert not await temp_manager.exists("todel.txt")

    @pytest.mark.asyncio
    async def test_temp_upload_file(self, temp_manager, tmp_path):
        """upload_file copies a file into the temp directory."""
        src = tmp_path / "src.txt"
        src.write_bytes(b"uploaded content")
        meta = await temp_manager.upload_file(src, "uploaded.txt")
        assert meta.name == "uploaded.txt"
        assert meta.size == len(b"uploaded content")

    @pytest.mark.asyncio
    async def test_temp_copy_file(self, temp_manager):
        """copy_file duplicates within temp directory."""
        await temp_manager.create_file("orig.txt", b"original")
        meta = await temp_manager.copy_file("orig.txt", "copy.txt")
        assert meta.name == "copy.txt"
        assert await temp_manager.exists("orig.txt")
        assert await temp_manager.exists("copy.txt")


class TestTempAutoCleanup:
    @pytest.mark.asyncio
    async def test_temp_auto_cleanup(self):
        """Files removed after context manager exit."""
        async with TempFileManager(prefix="test_ctx_", cleanup_on_exit=False) as mgr:
            await mgr.create_file("inside.txt", b"data")
            temp_dir = mgr._temp_dir
            assert temp_dir.exists()

        # After __aexit__, the directory should be cleaned up
        assert not temp_dir.exists()

    @pytest.mark.asyncio
    async def test_temp_context_manager_returns_self(self):
        """Async context manager returns the TempFileManager instance."""
        mgr = TempFileManager(prefix="test_ret_", cleanup_on_exit=False)
        async with mgr as m:
            assert m is mgr
        # Cleanup happened
        assert not mgr._temp_dir.exists()


class TestTempDownloadMoveSemantics:
    @pytest.mark.asyncio
    async def test_temp_download_moves_file(self, temp_manager, tmp_path):
        """download_file() moves file out of temp."""
        await temp_manager.create_file("moveme.txt", b"move me")
        dest = tmp_path / "output.txt"
        result = await temp_manager.download_file("moveme.txt", dest)
        assert dest.exists()
        assert dest.read_bytes() == b"move me"
        # Original should be gone (move semantics)
        assert not await temp_manager.exists("moveme.txt")

    @pytest.mark.asyncio
    async def test_temp_download_to_stream(self, temp_manager):
        """download_file() to stream copies content."""
        from io import BytesIO
        await temp_manager.create_file("stream.txt", b"streaming")
        buf = BytesIO()
        await temp_manager.download_file("stream.txt", buf)
        assert buf.getvalue() == b"streaming"


class TestTempSandboxing:
    @pytest.mark.asyncio
    async def test_temp_sandboxed(self):
        """Cannot escape temp directory."""
        mgr = TempFileManager(prefix="test_sandbox_", cleanup_on_exit=False)
        try:
            with pytest.raises(ValueError, match="traversal"):
                mgr._resolve_path("../../etc/passwd")
        finally:
            mgr.cleanup()


class TestTempBackwardCompat:
    def test_create_temp_file_static(self):
        """create_temp_file() static method works."""
        path = TempFileManager.create_temp_file(suffix=".txt", prefix="nav_test_")
        assert Path(path).exists()
        TempFileManager.remove_temp_file(path)
        assert not Path(path).exists()

    def test_remove_temp_file_nonexistent(self):
        """remove_temp_file() does not raise for missing files."""
        TempFileManager.remove_temp_file("/tmp/this_does_not_exist_12345.txt")
