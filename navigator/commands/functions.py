import asyncio
import contextlib
from navconfig.logging import logging
import aiofiles

def read_file(path, filename):
    f = open(path.joinpath("navigator", "commands", "templates", filename), "r")
    return f.read()


def create_dir(dir, name, py_package: bool = False):
    with contextlib.suppress(FileExistsError):
        path = dir.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
        if py_package:
            # create a __init__ file
            save_file(path, "__init__.py", content="#!/usr/bin/env python3")


def delete_file(dir, name):
    path = dir.joinpath(name)
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as err:
        print(err)
        return False


def save_file(dir, filename, content):
    try:
        loop = asyncio.get_event_loop()
        _new = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _new = True

    async def main(filename, content):
        try:
            path = dir.joinpath(filename)
            async with aiofiles.open(path, "w+") as afp:
                await afp.write(content)
            return True
        except Exception as err:
            print(err)
            logging.error(err)
            return False
    try:
        return loop.run_until_complete(main(filename, content))
    except Exception as err:
        print(err)
        logging.error(err)
        return False
    finally:
        if _new:
            loop.close()
