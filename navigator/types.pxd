# cython: language_level=3
# Copyright (C) 2018-present Jesus Lara
#
# Cython declaration file for ``navigator/types.pyx``.
#
# Spec FEAT-001 / TASK-006 — exposes the ``cdef`` attribute layout and
# ``cpdef`` surface of the :class:`URL` extension type to other Cython
# modules that may want to ``cimport`` it.
#
# NOTE: when a ``cdef class`` has a ``.pxd``, Cython requires that
# every ``cdef`` attribute be declared here *only* — the ``.pyx`` may
# not repeat them. TASK-006 therefore carries a small, mechanical
# knock-on edit in ``types.pyx`` (the attribute-declaration block is
# removed), tracked in the TASK-006 completion note.
from libcpp cimport bool


cdef class URL:
    cdef str value
    cdef str scheme
    cdef str path
    cdef str host
    cdef str port
    cdef str netloc
    cdef str query
    cdef str fragment
    cdef dict params
    cdef bool is_absolute

    cpdef URL change_scheme(self, str scheme)
    cpdef URL change_host(self, str host)
