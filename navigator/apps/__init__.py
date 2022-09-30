"""
Apps.

Application Logic for Navigator.

an Application is a subApp created inside of "apps" folder.
"""
import importlib
from types import ModuleType
from navconfig import (
    BASE_DIR
)
from navigator.utils.types import Singleton
# APP DIR
APP_DIR = BASE_DIR.joinpath("apps")


class ApplicationInstaller(metaclass=Singleton):
    """
    ApplicationInstaller.
        Class for getting Installed Apps in Navigator.
    """
    __initialized__ = False
    _apps_installed: list = []

    def installed_apps(self):
        return self._apps_installed

    def __init__(self):
        if self.__initialized__ is True:
            return
        self.__initialized__ = True
        if not APP_DIR.exists():
            return
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
