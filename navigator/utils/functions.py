# Copyright (C) 2018-present Jesus Lara
#
"""Navigator utility functions.

Pure-Python replacement for the former ``functions.pyx`` Cython module.

Spec FEAT-001 / TASK-002 — the Cython version wrapped a single
``logging.getLogger`` call, so Cython compilation offered no performance
benefit and was a maintenance burden. The ``SafeDict`` helper that lived
alongside ``get_logger`` has been removed: ``navigator/utils/__init__.py``
already re-exports ``SafeDict`` from :mod:`datamodel.typedefs.types`, so
the Cython copy was dead code.
"""
from __future__ import annotations

import logging as _stdlib_logging

from navconfig.logging import logging, loglevel


def get_logger(logger_name: str) -> _stdlib_logging.Logger:
    """Return a navconfig-configured logger for *logger_name*.

    Thin wrapper kept for API parity with the previous Cython
    implementation — external callers (notably
    ``navigator/handlers/base.py``) import it as-is.

    Args:
        logger_name: The logger name, forwarded to ``logging.getLogger``.

    Returns:
        A :class:`logging.Logger` instance whose level has been set from
        navconfig's ``loglevel``.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(loglevel)
    return logger
