"""ProgramConfig.

Program-based Application.
"""
import sys
import logging
import contextlib
from aiohttp.web import middleware
from aiohttp.web_urldispatcher import SystemRoute
from aiohttp import web, hdrs
from navigator_session import get_session
from .types import AppConfig
from ..responses import JSONResponse
from ..conf import (
    AUTH_SESSION_OBJECT
)
if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec

P = ParamSpec("P")


@middleware
async def program_session(request, handler):
    if isinstance(request.match_info.route, SystemRoute):  # eg. 404
        return await handler(request)
    # avoid authorization backend on excluded methods:
    if request.method == hdrs.METH_OPTIONS:
        return await handler(request)
    app = request.app
    program = app['program']
    program_slug = program.get_program()
    session = await get_session(request)
    try:
        user = session[AUTH_SESSION_OBJECT]
    except Exception as ex:
        raise web.HTTPUnauthorized(
            reason=f'NAV: Missing User Information: {ex}',
        ) from ex
    try:
        programs = user['programs']
    except (TypeError, KeyError, ValueError) as ex:
        raise web.HTTPBadRequest(
            reason=f'Bad Session Information: {ex!s}'
        ) from ex
    if program_slug not in programs:
        try:
            if 'superuser' in user['groups']:
                pass
            elif program_slug not in user['programs']:
                raise web.HTTPUnauthorized(
                    reason=f'NAV: You are not authorized to see this Program: {program_slug}',
                )
        except Exception as err:
            logging.warning(
                f'Program Middleware: {err}'
            )
        return await handler(request)
    # If we reach this point, the user is authorized for the program
    return await handler(request)


class ProgramConfig(AppConfig):
    _middleware: list = [program_session]
    template: str = '/templates'
    program_slug: str = ''
    enable_pgpool: bool = True

    def __init__(self, *args: P.args, **kwargs: P.kwargs):
        super(ProgramConfig, self).__init__(*args, **kwargs)
        self.app.router.add_get(
            '/authorize',
            self.program_authorization,
            name=f'{self.program_slug}_authorization'
        )

    async def program_authorization(self, request: web.Request) -> web.Response:
        session = await get_session(request)
        program_slug = self.program_slug
        # calculate the hierarchy:
        app = request.app
        try:
            user = session[AUTH_SESSION_OBJECT]
            user_id = user['user_id']
        except Exception as ex:
            raise web.HTTPUnauthorized(
                reason='NAV: Missing User Information: {ex}',
            ) from ex
        # try to know if the user has permission over this Program:
        with contextlib.suppress(KeyError):
            if 'superuser' in user['groups']:
                pass
            elif program_slug not in user['programs']:
                raise web.HTTPUnauthorized(
                    reason=f'NAV: You are not authorized to see this Program: {program_slug}',
                )
        return JSONResponse(
            {
                "status": "User Authorized",
                "id": user_id,
                "program": self.program_slug,
            },
            status=200
        )

    def get_program(self):
        return self.program_slug

    def get_program_id(self):
        return self.program_id

    async def on_startup(self, app):
        await super(ProgramConfig, self).on_startup(app)

    async def on_shutdown(self, app):
        await super(ProgramConfig, self).on_shutdown(app)
        logging.debug(f'ON SHUTDOWN {self._name}')
