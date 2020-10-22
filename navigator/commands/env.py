import asyncio
import logging
import sys
from pathlib import Path

from aiofile import AIOFile

from . import BaseCommand, CommandError

logger = logging.getLogger("Navigator.creator")
loop = asyncio.get_event_loop()


def read_file(path, filename):
    f = open(path.joinpath("navigator", "commands", "templates", filename), "r")
    return f.read()


def create_dir(dir, name):
    try:
        path = dir.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        pass


def save_file(dir, filename, content):
    async def main(filename, content):
        if content:
            path = dir.joinpath(Path(filename).resolve())
            async with AIOFile(path, "w+") as afp:
                await afp.write(content)
                await afp.fsync()
            return True
        else:
            return False

    return loop.run_until_complete(main(filename, content))


class EnvCommand(BaseCommand):
    help = "Enviroment Commands for Navigator"

    def parse_arguments(self, parser):
        parser.add_argument("--enable-notify", type=bool)
        parser.add_argument("--process-services", type=bool)

    def create(self, options, **kwargs):
        """
        Create can used to create a new Enviroment from scratch
        """
        path = Path(kwargs["project_path"]).resolve()

        env = read_file(path, "env.tpl")
        ini = read_file(path, "ini.tpl")
        settings = read_file(path, "settings.tpl")
        localsettings = read_file(path, "localsettings.tpl")
        run = read_file(path, "run.tpl")
        app = read_file(path, "app.tpl")

        output = "Enviroment Done."
        if options.debug:
            self.write(":: Creating a New Navigator Enviroment", level="INFO")
            self.write("= wait a few minutes", level="WARN")
        # apps, etc, env, services, settings, static/images/js/css, templates
        self.write("* First Step: Creating Directory structure")
        create_dir(path, "apps")
        create_dir(path, "env/testing")
        create_dir(path, "etc")
        create_dir(path, "services")
        create_dir(path, "settings")
        create_dir(path, "static/images")
        create_dir(path, "static/js")
        create_dir(path, "static/css")
        create_dir(path, "templates")
        self.write("* Second Step: Creation of Empty .env File")
        save_file(path, "env/.env", env)
        save_file(path, "env/testing/.env", env)
        save_file(path, "etc/navigator.ini", ini)
        self.write("* Third Step: Creation of Empty settings.py File")
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
        return output
