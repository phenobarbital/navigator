import asyncio
from collections.abc import Callable
from aiohttp import web
from navconfig.logging import logging
from datamodel.parsers.encoders import DefaultEncoder
from asyncdb.utils.functions import colors, cPrint

__all__ = ('colors', 'cPrint', )

async def run_cmd(cmd: list) -> str:
    print(f'Executing: {" ".join(cmd)}')
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
    out, error = await process.communicate()
    if error:
        raise Exception(error)
    return out.decode("utf8")


def json_response(response: web.Response, headers: dict = None, state: int = 200, cls: Callable = None):
    if cls is not None:
        logging.warning('Using *cls* is deprecated an will be removed soon.')
    fn = DefaultEncoder()
    jsonfn = fn.dumps
    obj = web.json_response(response, status=state, dumps=jsonfn)
    for header, value in headers.items():
        obj.headers[header] = value
    return obj
