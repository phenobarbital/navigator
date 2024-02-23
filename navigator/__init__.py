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
from .utils.uv import install_uvloop
try:
    from .navigator import Application
    from .responses import Response
except FileExistsError:
    pass
from .version import __title__, __description__, __version__, __author__

install_uvloop()

__all__ = (
    "Application",
    "Response",
)
