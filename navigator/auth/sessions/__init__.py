"""User sessions for Navigator and aiohttp.web server."""

__version__ = '0.0.1'

from aiohttp import web
import asyncio
import time
import logging
from .storages import SessionData
from navigator.conf import (
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
    SESSION_KEY,
    SESSION_STORAGE,
    SESSION_OBJECT
)

async def new_session(request: web.Request, userdata: dict = {}) -> SessionData:
    storage = request.get(SESSION_STORAGE)
    if storage is None:
        raise RuntimeError(
            "Missing Configuration for Session Middleware."
        )
    session = await storage.new_session(request, userdata)
    if not isinstance(session, SessionData):
        raise RuntimeError(
            "Installed {!r} storage should return session instance "
            "on .load_session() call, got {!r}.".format(storage, session))
    request[SESSION_OBJECT] = session
    return session

async def get_session(
        request: web.Request,
        userdata: dict = {},
        new: bool = False
) -> SessionData:
    session = request.get(SESSION_OBJECT)
    logging.debug(f'SESSION IS: {session!s} for object {SESSION_OBJECT!s}')
    if session is None:
        storage = request.get(SESSION_STORAGE)
        logging.debug(f'SESSION STORAGE IS {storage}')
        if storage is None:
            raise RuntimeError(
                "Missing Configuration for Session Middleware."
            )
        # using the storage session for Load an existing Session
        try:
            session = await storage.load_session(
                request=request,
                userdata=userdata,
                new=new
            )
        except Exception as err:
            raise RuntimeError(
                "Error Loading user Session."
            )
        request[SESSION_OBJECT] = session
        request['session'] = session
        if new is True and not isinstance(session, SessionData):
            raise RuntimeError(
                "Installed {!r} storage should return session instance "
                "on .load_session() call, got {!r}.".format(storage, session))
    return session
