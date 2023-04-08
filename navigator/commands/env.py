import asyncio
from pathlib import Path
from navconfig.logging import logging
from aiofile import AIOFile
from . import BaseCommand

logger = logging.getLogger("navigator.command")
loop = asyncio.get_event_loop()


def read_file(path, filename):
    f = open(path.joinpath("navigator", "commands", "templates", filename), "r", encoding='utf-8')
    return f.read()


def create_dir(directory, name, touch_init: bool = False):
    try:
        path = directory.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
        if touch_init is True:
            # create a __init__ file
            save_file(path, "__init__.py", content="#!/usr/bin/env python3")
    except FileExistsError as exc:
        logging.warning(f"{exc}")


def delete_file(directory, name):
    path = directory.joinpath(name)
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as exc:
        logging.warning(f"{exc}")
        return False


def save_file(directory, filename, content):
    async def main(filename, content):
        try:
            path = directory.joinpath(filename)
            async with AIOFile(path, "w+") as afp:
                await afp.write(content)
                await afp.fsync()
            return True
        except Exception as exc:
            logging.error(exc)
            return False
    return loop.run_until_complete(main(filename, content))


class EnvCommand(BaseCommand):
    help = "Creates ENV and etc/navigator.ini files for starting a Project."
    _version: str = "1.0.0"

    def configure(self):
        ### we don't need any
        self.add_argument("--enable_gunicorn", action="store_true")

    def create(self, options, **kwargs):
        """
        Create can used to create a new Environment from scratch
        """
        path = Path(kwargs["project_path"]).resolve()
        env = read_file(path, "env.tpl")
        ini = read_file(path, "ini.tpl")
        settings = read_file(path, "settings.tpl")
        localsettings = read_file(path, "localsettings.tpl")
        run = read_file(path, "run.tpl")
        app = read_file(path, "app.tpl")
        gunicorn_config = None
        if options.enable_gunicorn is True:
            gunicorn_config = read_file(path, "gunicorn_config.tpl")
            gunicorn = read_file(path, "nav.py.tpl")

        output = "Environment Done."
        if options.debug:
            self.write(":: Creating a New Navigator Environment", level="INFO")
            self.write("= wait a few minutes", level="WARN")
        # apps, etc, env, services, settings, static/images/js/css, templates
        self.write("* First Step: Creating Directory structure")
        create_dir(path, "apps", touch_init=True)
        create_dir(path, "env/testing")
        ### INI Path
        create_dir(path, "etc")
        create_dir(path, "log")
        create_dir(path, "settings", touch_init=True)
        create_dir(path, "static/images")
        create_dir(path, "static/js")
        create_dir(path, "static/css")
        create_dir(path, "templates")
        self.write("* Second Step: Creation of New .env File")
        save_file(path, "env/.env", env)
        ## also, saving an env for "testing" environment
        save_file(path, "env/testing/.env", env)
        save_file(path, "etc/navigator.ini", ini)
        # TODO: download from Google Drive, if possible
        self.write("* Third Step: Creation of Empty settings.py File *")
        save_file(path, "settings/settings.py", settings)
        save_file(path, "settings/local_settings.py.example", localsettings)
        self.write("* Fourt Step: Creation of a run.py File")
        save_file(path, "run.py", run)
        save_file(path, "app.py", app)
        self.write("* Fifth Step: adding a *home* template")
        home = read_file(path, "home.html")
        css = read_file(path, "styles.css")
        js = read_file(path, "scripts.js")
        save_file(path, "templates/home.html", home)
        save_file(path, "static/css/styles.css", css)
        save_file(path, "static/js/scripts.js", js)
        ## enable gunicorn configuration:
        if gunicorn_config:
            save_file(path, "gunicorn_config.py", gunicorn_config)
            save_file(path, "nav.py", gunicorn)
        return output
