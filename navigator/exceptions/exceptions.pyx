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
        super().__init__(message or f"Invalid Argument: {self.args!s}", 406)

cdef class ConfigError(NavException):

    def __init__(self, str message = None):
        super().__init__(message or f"Configuration Error.", 500)

### Errors:
cdef class ValidationError(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Bad Request: Validation Error", 410)

#### Authentication / Authorization
cdef class UserNotFound(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "User doesn't exists.", 404)

cdef class Unauthorized(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Unauthorized", 401)

cdef class InvalidAuth(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Invalid Authentication", 401)

cdef class FailedAuth(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Failed Authorization", 403)

cdef class AuthExpired(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Gone: Authentication Expired.", 410)

cdef class ActionError(NavException):

    def __init__(self, str message = None):
        super().__init__(message or "Action: Error", 400)
