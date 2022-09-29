# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
"""Navigator Exceptions."""


cdef class NavException(Exception):
    """Base class for other exceptions"""

    state: int = 0

    def __init__(self, str message, int state = 0, **kwargs):
        super().__init__(message)
        self.stacktrace = None
        if 'stacktrace' in kwargs:
            self.stacktrace = kwargs['stacktrace']
        self.message = message
        self.args = kwargs
        self.state = int(state)

    def __str__(self):
        return f"{__name__}: {self.message}"

    def get(self):
        return self.message

#### Exceptions:
cdef class InvalidArgument(NavException):

    def __init__(self, str message = None):
        super().__init__(406, message or f"Invalid Argument: {self.args!s}")

cdef class ConfigError(NavException):

    def __init__(self, str message = None):
        super().__init__(500, message or f"Configuration Error.")

### Errors:
cdef class ValidationError(NavException):

    def __init__(self, str message = None):
        super().__init__(410, message or "Bad Request: Validation Error")

#### Authentication / Authorization
cdef class UserNotFound(NavException):

    def __init__(self, str message = None):
        super().__init__(404, message or "User doesn't exists.")

cdef class Unauthorized(NavException):

    def __init__(self, str message = None):
        super().__init__(401, message or "Unauthorized")

cdef class InvalidAuth(NavException):

    def __init__(self, str message = None):
        super().__init__(401, message or "Invalid Authentication")

cdef class FailedAuth(NavException):

    def __init__(self, str message = None):
        super().__init__(403, message or "Failed Authorization")

cdef class AuthExpired(NavException):

    def __init__(self, str message = None):
        super().__init__(410, message or "Gone: Authentication Expired.")
