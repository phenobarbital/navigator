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


def drive_permission(client: str, secret: str, project: str = "navigator") -> str:
    permission = {
        "web": {
            "client_id": f"{client!s}.apps.googleusercontent.com",
            "project_id": project,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": secret,
            "redirect_uris": ["http://localhost:8090/"],
            "javascript_origins": ["http://localhost:8090"],
        }
    }
    return json.dumps(permission)


class EnvCommand(BaseCommand):
    help = "Enviroment Commands for Navigator"

    def parse_arguments(self, parser):
        parser.add_argument("--enable-notify", type=bool)
        parser.add_argument("--process-services", type=bool)
        parser.add_argument("--file_env", type=str)
        parser.add_argument("--client", type=str)
        parser.add_argument("--secret", type=str)
        parser.add_argument("--project", type=str)

    def create(self, options, **kwargs):
        """
        Create can used to create a new Enviroment from scratch
        """
        path = Path(kwargs["project_path"]).resolve()
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
        create_dir(path, "apps", touch_init=True)
        create_dir(path, "env/testing")
        create_dir(path, "etc")
        # create_dir(path, "log")
        create_dir(path, "services", touch_init=True)
        create_dir(path, "resources", touch_init=True)
        create_dir(path, "settings", touch_init=True)
        create_dir(path, "static/images")
        create_dir(path, "static/js")
        create_dir(path, "static/css")
        create_dir(path, "templates")
        self.write("* Second Step: Creation of Empty .env File")
        # save_file(path, "env/.env", env)
        # save_file(path, "env/testing/.env", env)
        save_file(path, "etc/navigator.ini", ini)
        # TODO: download from Google Drive, if possible
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

    def get_env(self, options, **kwargs):
        """get_env.

        Getting a new environment file from Google Drive.
        """
        path = Path(kwargs["project_path"]).resolve()
        file_env = options.file_env
        # first: removing existing credentials
        delete_file(path, "env/credentials.txt")
        # saving the credentials into a new file
        save_file(path, "env/file_env", file_env)
        # preparing the environment:
        # set SITE_ROOT:
        os.environ["SITE_ROOT"] = str(path)
        print("SITE ROOT: ", os.getenv("SITE_ROOT"))
        # set configuration for navconfig
        os.environ["NAVCONFIG_ENV"] = "drive"
        os.environ["NAVCONFIG_DRIVE_CLIENT"] = "env/credentials.txt"
        os.environ["NAVCONFIG_DRIVE_ID"] = file_env
        # get the drive permission
        client = options.client
        secret = options.secret
        project = options.project
        content = drive_permission(client, secret, project)
        save_file(path, "client_secrets.json", content)
        from navconfig import config

        config.save_environment("drive")
        return "Done."
