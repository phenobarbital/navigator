"""Tests for FileManagerInterface ABC and FileMetadata dataclass."""
import pytest
from datetime import datetime

from navigator.utils.file.abstract import FileManagerInterface, FileMetadata


class TestFileMetadata:
    """Tests for FileMetadata dataclass."""

    def test_file_metadata_creation(self):
        """FileMetadata instantiation with all fields."""
        meta = FileMetadata(
            name="test.txt",
            path="subdir/test.txt",
            size=1024,
            content_type="text/plain",
            modified_at=datetime(2026, 1, 1),
            url="file:///tmp/test.txt",
        )
        assert meta.name == "test.txt"
        assert meta.path == "subdir/test.txt"
        assert meta.size == 1024
        assert meta.content_type == "text/plain"
        assert meta.modified_at == datetime(2026, 1, 1)
        assert meta.url == "file:///tmp/test.txt"

    def test_file_metadata_optional_fields(self):
        """FileMetadata optional fields can be None."""
        meta = FileMetadata(
            name="data.bin",
            path="data.bin",
            size=0,
            content_type=None,
            modified_at=None,
            url=None,
        )
        assert meta.content_type is None
        assert meta.modified_at is None
        assert meta.url is None

    def test_file_metadata_is_dataclass(self):
        """FileMetadata is a proper dataclass."""
        import dataclasses
        assert dataclasses.is_dataclass(FileMetadata)


class TestFileManagerInterfaceABC:
    """Tests for FileManagerInterface ABC contract."""

    def test_cannot_instantiate_abc(self):
        """FileManagerInterface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            FileManagerInterface()

    def test_concrete_subclass_must_implement_all_abstract_methods(self):
        """Partial implementation raises TypeError on instantiation."""

        class PartialManager(FileManagerInterface):
            async def list_files(self, path="", pattern="*"):
                return []
            # Missing 8 other abstract methods

        with pytest.raises(TypeError):
            PartialManager()

    def test_full_implementation_instantiates(self):
        """Full implementation can be instantiated."""

        class FullManager(FileManagerInterface):
            async def list_files(self, path="", pattern="*"):
                return []
            async def get_file_url(self, path, expiry=3600):
                return ""
            async def upload_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def download_file(self, source, destination):
                from pathlib import Path
                return Path(source)
            async def copy_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def delete_file(self, path):
                return True
            async def exists(self, path):
                return False
            async def get_file_metadata(self, path):
                return FileMetadata("", "", 0, None, None, None)
            async def create_file(self, path, content):
                return True

        manager = FullManager()
        assert manager is not None

    @pytest.mark.asyncio
    async def test_create_from_text_concrete_helper(self):
        """create_from_text() calls create_file() with encoded bytes."""
        calls = []

        class TestManager(FileManagerInterface):
            async def list_files(self, path="", pattern="*"):
                return []
            async def get_file_url(self, path, expiry=3600):
                return ""
            async def upload_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def download_file(self, source, destination):
                from pathlib import Path
                return Path(source)
            async def copy_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def delete_file(self, path):
                return True
            async def exists(self, path):
                return False
            async def get_file_metadata(self, path):
                return FileMetadata("", "", 0, None, None, None)
            async def create_file(self, path, content):
                calls.append((path, content))
                return True

        m = TestManager()
        result = await m.create_from_text("hello.txt", "hello world")
        assert result is True
        assert calls == [("hello.txt", b"hello world")]

    @pytest.mark.asyncio
    async def test_create_from_bytes_with_bytesio(self):
        """create_from_bytes() handles BytesIO input."""
        from io import BytesIO
        calls = []

        class TestManager(FileManagerInterface):
            async def list_files(self, path="", pattern="*"):
                return []
            async def get_file_url(self, path, expiry=3600):
                return ""
            async def upload_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def download_file(self, source, destination):
                from pathlib import Path
                return Path(source)
            async def copy_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def delete_file(self, path):
                return True
            async def exists(self, path):
                return False
            async def get_file_metadata(self, path):
                return FileMetadata("", "", 0, None, None, None)
            async def create_file(self, path, content):
                calls.append(content)
                return True

        m = TestManager()
        buf = BytesIO(b"binary data")
        await m.create_from_bytes("file.bin", buf)
        assert calls[0] == b"binary data"

    @pytest.mark.asyncio
    async def test_find_files_default_implementation(self):
        """Default find_files() filters list_files() results."""

        class TestManager(FileManagerInterface):
            async def list_files(self, path="", pattern="*"):
                return [
                    FileMetadata("report.csv", "report.csv", 100, None, None, None),
                    FileMetadata("notes.txt", "notes.txt", 50, None, None, None),
                    FileMetadata("data.csv", "data.csv", 200, None, None, None),
                ]
            async def get_file_url(self, path, expiry=3600):
                return ""
            async def upload_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def download_file(self, source, destination):
                from pathlib import Path
                return Path(source)
            async def copy_file(self, source, destination):
                return FileMetadata("", "", 0, None, None, None)
            async def delete_file(self, path):
                return True
            async def exists(self, path):
                return False
            async def get_file_metadata(self, path):
                return FileMetadata("", "", 0, None, None, None)
            async def create_file(self, path, content):
                return True

        m = TestManager()
        # Filter by extension
        results = await m.find_files(extension=".csv")
        names = [r.name for r in results]
        assert "report.csv" in names
        assert "data.csv" in names
        assert "notes.txt" not in names

        # Filter by keyword
        results = await m.find_files(keywords="report")
        assert len(results) == 1
        assert results[0].name == "report.csv"
