# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
cdef class SafeDict(dict):
    """
    SafeDict.

    Allow to using partial format strings

    """
