# cython: language_level=3
# Copyright (C) 2018-present Jesus Lara
#
# Cython declaration file for ``navigator/utils/types.pyx``.
#
# Spec FEAT-001 / TASK-006 — exposes :class:`Singleton` to other Cython
# modules that may wish to ``cimport`` it. The ``_instances`` cache dict
# must be declared here (and not in the ``.pyx``) because Cython does
# not allow duplicate ``cdef`` declarations.


cdef class Singleton(type):
    cdef dict _instances
