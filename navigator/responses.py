"""
Various kinds of Application Responses.

TODO: add FileResponse or JSONResponse or SSEResponse (server-side).
"""
from typing import Any, Optional, Union
from pathlib import Path, PurePath
import io
import zipfile
from aiohttp import web
from aiohttp.web_exceptions import (
    HTTPNoContent,
)
from aiohttp_sse import sse_response, EventSourceResponse
from navigator.libs.json import json_encoder


__all__ = (
    "sse_response",
    "EventSourceResponse",
)


def Response(
    content: Any = None,
    text: Optional[str] = "",
    body: Any = None,
    status: int = 200,
    headers: dict = None,
    content_type: str = "text/plain",
    charset: Optional[str] = "utf-8",
) -> web.Response:
    """
    Response.
    Web Response Definition for Navigator
    """
    response = {"content_type": content_type, "charset": charset, "status": status}
    if headers:
        response["headers"] = headers
    if content and isinstance(content, str) or text is not None:
        response["text"] = content if content else text
    else:
        response["body"] = content if content else body
    return web.Response(**response)


def NoContent(
    headers: dict = None, content_type: str = "application/json"
) -> web.Response:
    response = {
        "content_type": content_type,
    }
    if headers:
        response["headers"] = headers
    response = HTTPNoContent(content_type=content_type)
    response.headers["Pragma"] = "no-cache"
    return response


def HTMLResponse(
    content: Any = None,
    text: Optional[str] = "",
    body: Any = None,
    status: int = 200,
    headers: dict = None,
) -> web.Response:
    """
    Sending response in HTML.
    """
    response = {
        "content": content,
        "text": text,
        "body": body,
        "headers": headers,
        "content_type": "text/html",
        "status": status,
    }
    return Response(**response)


def JSONResponse(
    content: Any,
    status: int = 200,
    headers: Optional[dict] = None,
    reason: Optional[str] = None,
    content_type: str = "application/json",
) -> web.Response:
    """
    JSONResponse.
     Sending responses using JSON.
    """
    response = {
        "content_type": content_type,
        "status": status,
        "dumps": json_encoder,
        "reason": reason,
    }
    if headers:
        response["headers"] = headers

    return web.json_response(content, **response)


async def FileResponse(
    file: Union[list, str, Path],
    request: web.Request,
    filename: str = 'file.zip',
    status: int = 200,
    headers: Optional[dict] = None,
):
    if isinstance(file, (str, PurePath)):
        return web.FileResponse(file, status=status, headers=headers)
    elif isinstance(file, list):
        ## iterate over all files, zipped and send the zipped buffer.
        # Create a buffer to store the ZIP archive
        zip_buffer = io.BytesIO()
        # Create a new ZIP archive in the buffer
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_archive:
            for f in file:
                if isinstance(f, str):
                    f = Path(f)
                # Add files to the ZIP archive
                zip_archive.write(f, f.name)
    # Set the buffer's file pointer to the beginning
    zip_buffer.seek(0)
# Create an aiohttp.StreamResponse
    response = web.StreamResponse(
        status=status,
        reason='OK',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
    response.content_type = 'application/zip'
    await response.prepare(request)
    # Write the ZIP buffer to the response
    await response.write(zip_buffer.read())
    # Signal that the body has been written
    await response.write_eof()
    # Return the response
    return response
