# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
"""Navigator Exceptions."""
cdef class NavException(Exception):
    """Base class for other exceptions"""
    pass

#### Exceptions:
cdef class InvalidArgument(NavException):
    pass

cdef class ConfigError(NavException):
    pass

#### Authentication / Authorization
cdef class UserNotFound(NavException):
    pass

cdef class Unauthorized(NavException):
    pass

cdef class InvalidAuth(NavException):
    pass

cdef class FailedAuth(NavException):
    pass

cdef class AuthExpired(NavException):
    pass

cdef class ValidationError(NavException):
    pass

cdef class ActionError(NavException):
    pass
