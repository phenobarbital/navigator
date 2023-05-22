import asyncio
from navconfig.logging import logging
from aiofile import AIOFile

def read_file(path, filename):
    f = open(path.joinpath("navigator", "commands", "templates", filename), "r")
    return f.read()


def create_dir(dir, name, py_package: bool = False):
    try:
        path = dir.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
        if py_package is True:
            # create a __init__ file
            save_file(path, "__init__.py", content="#!/usr/bin/env python3")
    except FileExistsError as exc:
        pass


def delete_file(dir, name):
    path = dir.joinpath(name)
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as err:
        print(err)
        return False


def save_file(dir, filename, content):
    loop = asyncio.get_event_loop()

    async def main(filename, content):
        try:
            path = dir.joinpath(filename)
            async with AIOFile(path, "w+") as afp:
                await afp.write(content)
                await afp.fsync()
            return True
        except Exception as err:
            print(err)
            logging.error(err)
            return False

    return loop.run_until_complete(main(filename, content))
