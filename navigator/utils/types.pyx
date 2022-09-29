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
    cdef dict _instances

    def __call__(object cls, *args, **kwargs):
        if cls._instances is None:
            cls._instances = {}
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    cdef object __new__(cls, args, kwargs):
        if cls._instances is None:
            cls._instances = {}
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__new__(cls, *args, **kwargs)
            setattr(cls, '__initialized__', True)
        return cls._instances[cls]
