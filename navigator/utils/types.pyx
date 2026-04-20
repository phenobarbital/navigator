# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
cdef class Singleton(type):
    """Singleton.
    Metaclass for Singleton instances.
    Returns:
        cls: a singleton version of the class, there are only one
        version of the instance any time.
    """
    # NOTE: ``cdef dict _instances`` moved to ``navigator/utils/types.pxd``
    # as part of FEAT-001 / TASK-006 (Cython does not allow declaring
    # the same cdef attribute in both .pxd and .pyx).

    def __call__(object cls, *args, **kwargs):
        if cls._instances is None:
            cls._instances = {}
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    # NOTE: the former ``cdef object __new__(cls, args, kwargs)`` method
    # was removed as part of FEAT-001 / TASK-006. It was dead code —
    # ``__call__`` already handles instance caching — and Cython refuses
    # to compile a ``cdef __new__`` alongside a ``.pxd`` (the method is
    # declared but Cython will not accept a matching definition). No
    # production code called ``Singleton.__new__`` directly (verified
    # via grep across the repo), so removing it is a pure cleanup.
