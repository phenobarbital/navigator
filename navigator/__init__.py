"""NAVIGATOR.

Navigator is a simple framework to build asyncio-based applications, full
of features similar to django as Applications, domains and sub-domains.

Run:
    Run Navigator works simply to load run.py::

        $ python run.py

Section breaks are created by resuming unindented text. Section breaks
are also implicitly created anytime a new section starts.

Attributes:
    * WIP

Todo:
    * Work with asgi loaders
    * You have to also use ``sphinx.ext.todo`` extension

.. More information in:
https://github.com/phenobarbital/navigator-api

"""
from .navigator import Application, Response, get_version

__all__ = (Application, Response, get_version)
