import asyncio
from typing import List
import json
import rapidjson
import inspect
from functools import partial
from aiohttp import web
from asyncdb.utils.encoders import BaseEncoder

async def run_cmd(cmd: List) -> str:
    print(f'Executing: {" ".join(cmd)}')
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
    out, error = await process.communicate()
    if error:
        raise Exception(error)
    return out.decode("utf8")


def escapeString(value):
    v = value if value != "None" else ""
    v = str(v).replace("'", "''")
    v = "'{}'".format(v) if type(v) == str else v
    return v


def json_response(response={}, headers={}, state=200, cls=None):
    if cls is not None:
        if inspect.isclass(cls):
            # its a class-based Encoder
            jsonfn = partial(json.dumps, cls=cls)
        else:
            # its a function
            jsonfn = partial(json.dumps, default=cls)
    else:
        jsonfn = partial(json.dumps, cls=BaseEncoder)
    obj = web.json_response(response, status=state, dumps=jsonfn)
    for header, value in headers.items():
        obj.headers[header] = value
    return obj
