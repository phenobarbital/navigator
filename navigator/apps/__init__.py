"""
Apps.

Application Logic for Navigator.

an Application is a subApp created inside of "apps" folder.
"""
import importlib
from types import ModuleType
from navigator.types import Singleton
from navigator.exceptions import NavException
from navconfig import (
    BASE_DIR
)
from typing import List

APP_DIR = BASE_DIR.joinpath("apps")

if not APP_DIR.is_dir():
    raise NavException(
        'Navigator: *apps* Folder is missing.'
    )

class ApplicationInstaller(metaclass=Singleton):
    """
    ApplicationInstaller.
        Class for getting Installed Apps in Navigator.
    """
    __initialized = False
    _apps_installed: List = []

    def installed_apps(self):
        return self._apps_installed

    def __init__(self, *args, **kwargs):
        if self.__initialized is True:
            return
        self.__initialized = True
        for item in APP_DIR.iterdir():
            if item.name != "__pycache__":
                if item.is_dir():
                    name = item.name
                    if not name in self._apps_installed:
                        # TODO: avoid load apps.dataintegration
                        app_name = f"apps.{item.name}"
                        # path = APP_DIR.joinpath(name)
                        # url_file = path.joinpath("urls.py")
                        try:
                            i = importlib.import_module(app_name, package="apps")
                            if isinstance(i, ModuleType):
                                # is a Navigator Program
                                self._apps_installed += (app_name,)
                        except ImportError as err:
                            print("ERROR: ", err)
                            continue
