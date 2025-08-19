"""NAVIGATOR.

Navigator is a simple framework to build asyncio-based applications, full
of features similar to django as Applications, domains and sub-domains.

Run:
    Run Navigator works simply to load run.py::

        $ python run.py

    Can also be launched using Gunicorn:

        $ gunicorn nav:navigator -c gunicorn_config.py

TODO:
    * Work with asgi loaders
    * You have to also use ``sphinx.ext.todo`` extension

.. More information in:
https://github.com/phenobarbital/navigator

"""
from .version import (
    __title__,
    __description__,
    __version__,
    __author__,
    __author_email__,
    __copyright__,
    __license__
)
try:
    from .navigator import Application
    from .responses import Response
    from .utils.uv import install_uvloop
    install_uvloop()
except ImportError:
    # uvloop is not installed, continue without it
    pass

def version():
    """version.
    Returns:
        str: current version of Navigator flowtask.
    """
    return __version__

__all__ = (
    "Application",
    "Response",
    "version",
    "__title__",
    "__description__",
    "__version__",
    "__author__",
)
