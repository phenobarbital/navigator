import os
import sys
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

### printing functions
class colors:
    """
    Colors class.

       reset all colors with colors.reset;
       Use as colors.subclass.colorname.
    i.e. colors.fg.red or colors.fg.greenalso, the generic bold, disable,
    underline, reverse, strike through,
    and invisible work with the main class i.e. colors.bold
    """

    reset = "\033[0m"
    bold = "\033[01m"
    disable = "\033[02m"
    underline = "\033[04m"
    reverse = "\033[07m"
    strikethrough = "\033[09m"
    invisible = "\033[08m"

    class fg:
        """
        colors.fg.

        Foreground Color subClass
        """

        black = "\033[30m"
        red = "\033[31m"
        green = "\033[32m"
        orange = "\033[33m"
        blue = "\033[34m"
        purple = "\033[35m"
        cyan = "\033[36m"
        lightgrey = "\033[37m"
        darkgrey = "\033[90m"
        lightred = "\033[91m"
        lightgreen = "\033[92m"
        yellow = "\033[93m"
        lightblue = "\033[94m"
        pink = "\033[95m"
        lightcyan = "\033[96m"


def cPrint(msg, color=None, level="INFO"):
    try:
        if color is not None:
            coloring = colors.bold + getattr(colors.fg, color)
        elif level:
            if level == "INFO":
                coloring = colors.bold + colors.fg.green
            elif level == "SUCCESS":
                coloring = colors.bold + colors.fg.lightgreen
            elif level == "NOTICE":
                coloring = colors.fg.blue
            elif level == "DEBUG":
                coloring = colors.fg.lightblue
            elif level == "WARN":
                coloring = colors.bold + colors.fg.yellow
            elif level == "ERROR":
                coloring = colors.fg.lightred
            elif level == "CRITICAL":
                coloring = colors.bold + colors.fg.red
        else:
            coloring = colors.reset
    except Exception as err:
        print("Wrong color schema {}, error: {}".format(color, str(err)))
        coloring = colors.reset
    print(coloring + msg, colors.reset)
