"""Tests for FileServingExtension web serving layer."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

from aiohttp import web

from navigator.utils.file.web import FileServingExtension
from navigator.utils.file.abstract import FileManagerInterface, FileMetadata
from navigator.utils.file.local import LocalFileManager


# ── Mock manager ──────────────────────────────────────────────────────────

def _make_mock_manager(
    file_exists=True,
    file_size=11,
    content=b"hello world",
    content_type="text/plain",
):
    """Return a mock FileManagerInterface."""
    mock = MagicMock(spec=FileManagerInterface)
    mock.manager_name = "testmgr"
    mock.exists = AsyncMock(return_value=file_exists)
    mock.get_file_metadata = AsyncMock(return_value=FileMetadata(
        name="test.txt",
        path="test.txt",
        size=file_size,
        content_type=content_type,
        modified_at=None,
        url=None,
    ))

    async def download_file(path, dest):
        dest.write(content)
        return Path(path)

    mock.download_file = download_file
    return mock


class TestFileServingExtensionSetup:
    def test_setup_registers_route(self):
        """setup(app) registers GET route correctly."""
        mock_manager = _make_mock_manager()
        ext = FileServingExtension(manager=mock_manager, route="/files")

        app = web.Application()
        returned = ext.setup(app)

        # Verify route was registered (check router resources)
        routes = [str(r) for r in app.router.resources()]
        assert any("/files" in r for r in routes)

    def test_setup_stores_extension_in_app(self):
        """setup(app) stores extension in app context."""
        mock_manager = _make_mock_manager()
        ext = FileServingExtension(
            manager=mock_manager, route="/data", manager_name="testmgr"
        )
        app = web.Application()
        ext.setup(app)
        assert "testmgr" in app

    def test_setup_uses_manager_name(self):
        """Extension name defaults to manager's manager_name."""
        from navigator.utils.file.local import LocalFileManager
        import tempfile, pathlib
        td = pathlib.Path(tempfile.mkdtemp())
        mgr = LocalFileManager(base_path=td)
        ext = FileServingExtension(manager=mgr, route="/local")
        assert ext.name == "localfile"
        import shutil
        shutil.rmtree(td, ignore_errors=True)


class TestFileServingHandleFile:
    @pytest.mark.asyncio
    async def test_web_serving_404_missing_file(self):
        """Missing file returns 404."""
        mock_manager = _make_mock_manager(file_exists=False)
        ext = FileServingExtension(manager=mock_manager, route="/data")

        request = MagicMock()
        request.match_info = {"filepath": "missing.txt"}
        request.headers = {}

        response = await ext.handle_file(request)
        assert response.status == 404

    @pytest.mark.asyncio
    async def test_web_serving_empty_path_raises_404(self):
        """Empty filepath raises HTTPNotFound."""
        mock_manager = _make_mock_manager()
        ext = FileServingExtension(manager=mock_manager, route="/data")

        request = MagicMock()
        request.match_info = {"filepath": ""}
        request.headers = {}

        with pytest.raises(web.HTTPNotFound):
            await ext.handle_file(request)

    @pytest.mark.asyncio
    async def test_web_serving_traversal_blocked(self):
        """Path traversal returns 403."""
        mock_manager = _make_mock_manager()
        ext = FileServingExtension(manager=mock_manager, route="/data")

        request = MagicMock()
        request.match_info = {"filepath": "../etc/passwd"}
        request.headers = {}

        response = await ext.handle_file(request)
        assert response.status == 403


class TestRangeRequests:
    def test_parse_range_header_valid(self):
        """_parse_range_header returns correct offsets."""
        start, end = FileServingExtension._parse_range_header("bytes=0-99", 1000)
        assert start == 0
        assert end == 99

    def test_parse_range_header_open_end(self):
        """_parse_range_header handles open-ended range."""
        start, end = FileServingExtension._parse_range_header("bytes=100-", 500)
        assert start == 100
        assert end == 499

    def test_parse_range_header_invalid_unit(self):
        """_parse_range_header raises for non-byte ranges."""
        with pytest.raises(web.HTTPBadRequest):
            FileServingExtension._parse_range_header("items=0-9", 100)

    def test_parse_range_header_out_of_bounds(self):
        """_parse_range_header raises for out-of-bounds range."""
        with pytest.raises(web.HTTPRequestRangeNotSatisfiable):
            FileServingExtension._parse_range_header("bytes=0-999", 100)


class TestBackwardCompatMethods:
    def test_backward_compat_setup(self, tmp_path):
        """manager.setup(app) still works (delegates to extension)."""
        mgr = LocalFileManager(base_path=tmp_path)
        app = web.Application()
        returned = mgr.setup(app, route="/local")
        # Route should be registered
        routes = [str(r) for r in app.router.resources()]
        assert any("/local" in r for r in routes)

    @pytest.mark.asyncio
    async def test_backward_compat_handle_file(self, tmp_path):
        """manager.handle_file(request) delegates to FileServingExtension."""
        (tmp_path / "test.txt").write_bytes(b"content")
        mgr = LocalFileManager(base_path=tmp_path)

        request = MagicMock()
        request.match_info = {"filepath": "test.txt"}
        request.headers = {}

        mock_response = MagicMock()
        mock_response.status = 200

        # Patch FileServingExtension.handle_file to avoid real HTTP streaming
        # (which requires a real aiohttp request object with internal state)
        with patch.object(
            FileServingExtension, "handle_file",
            new=AsyncMock(return_value=mock_response),
        ):
            response = await mgr.handle_file(request)

        assert response is not None
        assert response.status == 200


class TestWebServingLocalIntegration:
    """Integration test using aiohttp test client and LocalFileManager."""

    @pytest.mark.asyncio
    async def test_web_serving_local(self, tmp_path, aiohttp_client):
        """FileServingExtension serves local files via aiohttp test client."""
        (tmp_path / "hello.txt").write_bytes(b"hello world")
        mgr = LocalFileManager(base_path=tmp_path)

        app = web.Application()
        ext = FileServingExtension(manager=mgr, route="/files")
        ext.setup(app)

        client = await aiohttp_client(app)
        resp = await client.get("/files/hello.txt")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_web_serving_404(self, tmp_path, aiohttp_client):
        """Missing file returns 404."""
        mgr = LocalFileManager(base_path=tmp_path)

        app = web.Application()
        ext = FileServingExtension(manager=mgr, route="/files")
        ext.setup(app)

        client = await aiohttp_client(app)
        resp = await client.get("/files/nonexistent.txt")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_web_serving_range_request(self, tmp_path, aiohttp_client):
        """Range request returns HTTP 206 with correct Content-Range."""
        content = b"hello world"
        (tmp_path / "range.txt").write_bytes(content)
        mgr = LocalFileManager(base_path=tmp_path)

        app = web.Application()
        ext = FileServingExtension(manager=mgr, route="/files")
        ext.setup(app)

        client = await aiohttp_client(app)
        resp = await client.get(
            "/files/range.txt",
            headers={"Range": "bytes=0-4"}
        )
        assert resp.status == 206
        assert "Content-Range" in resp.headers
        body = await resp.read()
        assert body == b"hello"
