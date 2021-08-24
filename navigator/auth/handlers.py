# -*- coding: utf-8 -*-
#!/usr/bin/env python3

import asyncio
import base64
import json
import os
import sys

from aiohttp import web

from navigator.conf import (
    DEBUG,
    SESSION_PREFIX,
    SESSION_URL,
    config
)
from navigator.handlers import nav_exception_handler
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from aiohttp_session import get_session, new_session
from navigator.views import BaseView


class UserHandler(BaseView):
    async def profile(self):
        pass

    async def get(self):
        session = None
        try:
            session = await get_session(self.request)
        except Exception as err:
            print(err)
            return self.critical(
                request=self.request,
                exception=err
            )
        try:
            if not session:
                headers = {"x-status": "Empty", "x-message": "Invalid User Session"}
                return self.no_content(headers=headers)
            else:
                try:
                    sessionid = session['id']
                except KeyError:
                    return self.error('Invalid Session, missing Session ID')
                headers = {"x-status": "OK", "x-message": "Session OK"}
                data = {
                    "key": sessionid,
                    "session_id": sessionid,
                    **session[sessionid]
                }
                if data:
                    return self.json_response(
                        response=data,
                        headers=headers
                    )
        except Exception as err:
            return self.error(
                self.request,
                exception=err
            )

    async def logout(self, request):
        app = request.app
        router = app.router
        auth = app["auth"]
        try:
            session = await get_session(request)
            session.invalidate()
        except Exception as err:
            print(err, err.__class__.__name__)
            raise NavException(err, state=501)
        # return a redirect to LOGIN
        return web.HTTPFound(router["login"].url_for())

    async def delete(self):
        return await self.logout(self.request)
