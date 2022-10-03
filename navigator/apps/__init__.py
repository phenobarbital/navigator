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
try:
    from navconfig.conf import (
        APPLICATIONS
    )
except ImportError:
    APPLICATIONS = []

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
                        app_name = f"apps.{item.name}"
                        try:
                            i = importlib.import_module(app_name, package="apps")
                            if isinstance(i, ModuleType):
                                # is a Navigator Program
                                self._apps_installed.append((app_name, i))
                        except ImportError as err:
                            # HERE, there is no module
                            print("ERROR: ", err)
                            continue
        for name in APPLICATIONS:
            ## Fallback Application (avoid calling too much app initialization)
            app_name = f"apps.{name}"
            if not name in self._apps_installed:
                # virtual app, fallback app:
                self._apps_installed.append((app_name, None))
