"""
Application Startup.

Application Logic for Navigator.

an Application is a subApp created inside of "apps" folder.
"""
import importlib
from types import ModuleType
try:
    from aiohttp.web import AppKey
except ImportError:
    pass
from navconfig.logging import logging
from navconfig import BASE_DIR

try:
    from navconfig.conf import APPLICATIONS
except ImportError:
    APPLICATIONS = []
from ..types import WebApp
from ..handlers.types import AppConfig
from ..utils.types import Singleton

# APP DIR
APP_DIR = BASE_DIR.joinpath("apps")


class ApplicationInstaller(metaclass=Singleton):
    """
    ApplicationInstaller.
        Class for getting Installed Apps in Navigator.
    """

    __initialized__ = False
    _apps_installed: list = []
    _apps_names: list[str] = []

    def installed_apps(self):
        return self._apps_installed

    def app_list(self) -> list:
        return self._apps_names

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
                    if name not in self._apps_installed:
                        app_name = f"apps.{item.name}"
                        try:
                            i = importlib.import_module(app_name, package="apps")
                            if isinstance(i, ModuleType):
                                # is a Navigator Program
                                self._apps_installed.append((app_name, i))
                                self._apps_names.append(app_name)
                        except ImportError as err:
                            # HERE, there is no module
                            print("ERROR: ", err)
                            continue
        for name in APPLICATIONS:
            ## Fallback Application (avoid calling too much app initialization)
            app_name = f"apps.{name}"
            if name not in self._apps_installed:
                # virtual app, fallback app:
                self._apps_installed.append((app_name, None))
                self._apps_names.append(app_name)


#######################
##
## APPS CONFIGURATION
##
#######################
def app_startup(app_list: list, app: WebApp, context: dict = None, **kwargs):
    """Initialize all Apps in the existing Installation."""
    for apps in app_list:
        obj = None
        app_name, app_class = apps  # splitting the tuple
        try:
            instance_app = None
            name = app_name.split(".")[1]
            if app_class is not None:
                obj = getattr(app_class, name)
                instance_app = obj(app_name=name, context=context, **kwargs)
                domain = getattr(instance_app, "domain", None)
            else:
                ## TODO: making a default App configurable.
                instance_app = AppConfig(app_name=name, context=context, **kwargs)
                instance_app.__class__.__name__ = name
                domain = None
            sub_app = instance_app.App
            if domain:
                app.add_domain(domain, sub_app)
                # TODO: adding as sub-app as well
            else:
                app.add_subapp(f"/{name}/", sub_app)
            # TODO: build automatic documentation
            try:
                # can I add Main to subApp?
                # main_key = AppKey("Main", WebApp)
                # sub_app[main_key] = app
                sub_app['Main'] = app
                for name, ext in app.extensions.items():
                    # sub_key = AppKey(name, WebApp)
                    # sub_app[sub_key] = ext
                    sub_app[name] = ext
                    sub_app.extensions[name] = ext
            except (KeyError, AttributeError) as err:
                logging.warning(err)
        except ImportError as err:
            logging.warning(err)
            continue
