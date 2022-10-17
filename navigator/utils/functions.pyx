# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
from navconfig.logging import logging, loglevel


def get_logger(str logger_name):
    """get_logger.

    Get a logger from navconfig (already configured.)
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(loglevel)
    return logger


cdef class SafeDict(dict):
    """
    SafeDict.

    Allow to using partial format strings

    """
    def __missing__(self, str key):
        """Missing method for SafeDict."""
        return "{" + key + "}"
