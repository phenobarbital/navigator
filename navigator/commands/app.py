"""
Base Command for App Creation.
"""
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

from aiofile import AIOFile

from . import BaseCommand, CommandError


logger = logging.getLogger('navigator')
loop = asyncio.get_event_loop()


def read_file(path, filename):
    f = open(path.joinpath("navigator", "commands", "templates", filename), "r")
    return f.read()


def create_dir(dir, name, touch_init: bool = False):
    try:
        path = dir.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
        if touch_init is True:
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


class AppCommand(BaseCommand):
    help = "Application Creation Commands for Navigator"

    def parse_arguments(self, parser):
        parser.add_argument("--program", type=str)
        parser.add_argument("--is_program", type=bool)
        parser.add_argument("--file_ini", type=str)
        parser.add_argument("--enable_models", type=bool)

    def create(self, options, **kwargs):
        """
        Create can used to create a new Application from scratch
        """
        path = Path(kwargs["project_path"]).resolve()
        try:
            urls = read_file(path, "urls.py.tpl")
            ini = read_file(path, "init.app.tpl")
            views = read_file(path, "views.py.tpl")
        except Exception as err:
            self.write(f":: Error getting templates: {err!s}", level="WARN")
            self.write(f":: Directory: {path!s}", level="WARN")
            output = "Failed."
            return output

        output = "Application Created."
        if options.debug:
            self.write(":: Creating a New Navigator Application", level="INFO")
            self.write("= wait a few seconds", level="WARN")
        # apps, etc, env, services, settings, static/images/js/css, templates
        self.write("* First Step: Creating Directory structure")
        create_dir(path, "apps", touch_init=True)
        app_path = path.joinpath('apps')

        try:
            program = options.program
        except Exception as err:
            self.write(f":: Error getting Program: {err!s}", level="ERROR")
            output = "Failed."
            return output

        if options.is_program:
            ini = read_file(path, "program.app.tpl")

        ini = ini.format(program=program)
        # first: create the program path:
        create_dir(app_path, program)
        # also, the template folder
        program_path = app_path.joinpath(program)
        create_dir(program_path, "templates")
        create_dir(program_path, "images")

        self.write("* Second Step: Creation of Empty Application Structure")
        save_file(program_path, "__init__.py", ini)
        if options.file_ini:
            # create an empty ini file:
            save_file(path, f"{program}.ini")


        # saving urls and views files:
        save_file(program_path, "urls.py", urls)
        save_file(program_path, "views.py", views)

        if options.enable_models:
            models = read_file(path, "models.py.tpl")
            save_file(program_path, "models.py", models)
        return output
