"""
Base Command for App Creation.
"""
import asyncio
import logging
from pathlib import Path
from . import BaseCommand
from .functions import read_file, create_dir, save_file

logger = logging.getLogger("navigator")
loop = asyncio.get_event_loop()

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
        app_path = path.joinpath("apps")

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
