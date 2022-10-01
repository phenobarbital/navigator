"""NAV Extension is a Helper to build Pluggable extensions."""
import sys
from typing import (
    Optional
)
from collections.abc import Callable
from abc import ABC
from navconfig import config
from navconfig.logging import logging
from navigator.exceptions import NavException, ConfigError
from navigator.types import WebApp

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec
P = ParamSpec("P")


class ExtensionError(NavException):
    """Useful for raise errors from Extensions."""


class BaseExtension(ABC):
    """BaseExtension.

    Description: Base Class for all NAV Extensions.
    """
    name: str = None # Optional name for adding the extension on App context.
    app: WebApp = None

    # Signal for any startup method on application.
    on_startup: Optional[Callable] = None

    # Signal for any shutdown process (will registered into App).
    on_shutdown: Optional[Callable] = None

    # adding custom middlewares to app (if needed)
    middleware: Optional[Callable] = None

    def __init__(
            self,
            *args: P.args,
            app_name: str = None,
            **kwargs: P.kwargs
        ) -> None:
        ### added config support
        self.config: config
        if app_name:
            self.name = app_name # override name
        self._args = args
        self._kwargs = kwargs
        ## name of the extension:
        self.__name__ = self.__class__.__name__


    def setup(self, app: WebApp) -> WebApp:
        self.app = app # register the app into the Extension
        # and register the extension into the app
        app[self.name] = self
        logging.debug(f':::: Extension {self.__name__} Loaded ::::')

        # add a middleware to the app
        if callable(self.middleware):
            try:
                mdl = app.middlewares
                 # add the middleware
                mdl.append(self.middleware)
            except Exception as err:
                logging.exception(
                    f"Error loading Extension Middleware {self.name} init: {err!s}"
                )
                raise ConfigError(
                    f"Error loading Extension Middleware {self.name} init: {err!s}"
                ) from err

        # adding signals for startup and shutdown:
        # startup operations over extension backend
        if callable(self.on_startup):
            app.on_startup.append(
                self.on_startup
            )
        # cleanup operations over extension backend
        if callable(self.on_shutdown):
            app.on_cleanup.append(
                self.on_cleanup
            )
        return app
