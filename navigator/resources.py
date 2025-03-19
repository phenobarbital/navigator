#!/usr/bin/env python
import asyncio
import random
import uuid
from pathlib import Path
from aiohttp import WSMsgType, web
from navconfig import BASE_DIR
from navconfig.logging import logging, logger
from navigator_session import get_session
from .libs.json import json_encoder


async def ping(request: web.Request):
    """
    ---
    summary: This end-point allow to test that service is up.
    tags:
    - Health check
    produces:
    - text/plain
    responses:
        "200":
            description: successful operation. Return "pong" text
        "405":
            description: invalid HTTP Method
    """
    return web.Response(text="PONG")


async def home(request: web.Request):
    """
    ---
    summary: This end-point is the default "home" for all newly projects
    tags:
    - Home
    - Index
    produces:
    - text/html
    responses:
        "200":
            description: template "templates/home.html" returned.
        "404":
            description: Template "templates/home.html" not found.
    """
    path = Path(BASE_DIR).joinpath("navigator/templates/home.html")
    try:
        file_path = path
        if not file_path.exists():
            return web.HTTPNotFound(
                reason="Template not found: navigator/templates/home.html"
            )
        return web.FileResponse(file_path)
    except Exception as e:  # pylint: disable=W0703
        response_obj = {"status": "failed", "reason": str(e)}
        return web.Response(
            text=json_encoder(response_obj), status=500, content_type="application/json"
        )
