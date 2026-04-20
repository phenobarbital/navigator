# Copyright (C) 2018-present Jesus Lara
#
"""Navigator Exceptions.

Pure-Python replacement for the former ``exceptions.pyx`` Cython module.

Spec FEAT-001 / TASK-002 — the Cython version provided no measurable
performance benefit for exception instantiation, so the module is now
plain Python. The public API (class names, ``state`` codes, ``__init__``
signatures, ``__str__`` format, ``.get()`` method) is preserved exactly
for backward compatibility.
"""
from __future__ import annotations


class NavException(Exception):
    """Base class for all Navigator exceptions.

    Attributes:
        state: HTTP-like status code associated with this exception class.
            Subclasses override the default.
        message: The human-readable message passed to ``__init__``.
        stacktrace: Optional stacktrace string (from ``stacktrace`` kwarg).
        args: Preserves the ``kwargs`` dict passed to ``__init__``
            (intentional override of ``Exception.args`` for backward compat
            with the Cython implementation).
    """

    state: int = 0

    def __init__(self, message: str = "", state: int = 0, **kwargs) -> None:
        super().__init__(message)
        self.stacktrace = kwargs.get("stacktrace")
        self.message = message
        # NOTE: the Cython original overrides ``self.args`` with the kwargs
        # dict. Preserved here for strict API parity — callers rely on it.
        self.args = kwargs
        self.state = int(state)

    def __str__(self) -> str:
        return f"{__name__}: {self.message}"

    def get(self) -> str:
        return self.message


# --------------------------------------------------------------------------
# Input validation / configuration errors
# --------------------------------------------------------------------------

class InvalidArgument(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or f"Invalid Argument: {self.args!s}", 406)


class ConfigError(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Configuration Error.", 500)


class ValidationError(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bad Request: Validation Error", 410)


# --------------------------------------------------------------------------
# Authentication / Authorization
# --------------------------------------------------------------------------

class UserNotFound(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "User doesn't exists.", 404)


class Unauthorized(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Unauthorized", 401)


class InvalidAuth(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Invalid Authentication", 401)


class FailedAuth(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Failed Authorization", 403)


class AuthExpired(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Gone: Authentication Expired.", 410)


# --------------------------------------------------------------------------
# Action-related errors
# --------------------------------------------------------------------------

class ActionError(NavException):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Action: Error", 400)
