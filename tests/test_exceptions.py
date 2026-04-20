"""Exception API parity tests.

Verify the pure-Python :mod:`navigator.exceptions.exceptions` (TASK-002)
behaves identically to the former Cython ``cdef class`` version:

* default ``state`` codes match the spec table,
* ``__init__`` accepts ``message`` + ``state`` + ``**kwargs``,
* ``__str__`` follows the ``"navigator.exceptions.exceptions: <msg>"``
  format,
* ``.get()`` returns the stored ``message``,
* ``stacktrace`` kwarg is preserved on the instance,
* ``self.args`` is overridden to hold the ``kwargs`` dict (legacy API
  contract).
"""
from __future__ import annotations

import pytest

from navigator.exceptions import (
    AuthExpired,
    ConfigError,
    FailedAuth,
    InvalidArgument,
    InvalidAuth,
    NavException,
    Unauthorized,
    UserNotFound,
    ValidationError,
)


class TestNavException:
    def test_default_state(self):
        exc = NavException("test")
        assert exc.state == 0
        assert exc.message == "test"

    def test_custom_state(self):
        exc = NavException("test", state=404)
        assert exc.state == 404

    def test_str_format(self):
        exc = NavException("test message")
        rendered = str(exc)
        assert "test message" in rendered
        # The module-qualified prefix must remain stable for callers that
        # grep/parse it (e.g. log aggregation rules).
        assert rendered.startswith("navigator.exceptions.exceptions:")

    def test_get_returns_message(self):
        exc = NavException("hello")
        assert exc.get() == "hello"

    def test_stacktrace_kwarg(self):
        exc = NavException("boom", stacktrace="trace here")
        assert exc.stacktrace == "trace here"

    def test_args_override_holds_kwargs(self):
        """Legacy behavior: ``self.args`` is set from the kwargs dict.

        :class:`BaseException` coerces whatever is assigned to ``args`` into a
        tuple (its C-level setter iterates the value), so the original Cython
        code's ``self.args = kwargs`` lands as a tuple of the kwargs keys.
        The pure-Python implementation reproduces that same behavior — this
        test locks it in.
        """
        exc = NavException("x", stacktrace="t", extra=1)
        # Only the keys survive the tuple coercion; order follows the
        # dict-insertion order (3.7+ guarantee).
        assert exc.args == ("stacktrace", "extra")
        # ``stacktrace`` is still accessible as an attribute.
        assert exc.stacktrace == "t"

    def test_state_is_coerced_to_int(self):
        exc = NavException("x", state="418")
        assert exc.state == 418


class TestExceptionSubclasses:
    @pytest.mark.parametrize(
        "cls,expected_state",
        [
            (InvalidArgument, 406),
            (ConfigError, 500),
            (ValidationError, 410),
            (UserNotFound, 404),
            (Unauthorized, 401),
            (InvalidAuth, 401),
            (FailedAuth, 403),
            (AuthExpired, 410),
        ],
    )
    def test_default_states(self, cls, expected_state):
        exc = cls()
        assert exc.state == expected_state

    @pytest.mark.parametrize(
        "cls",
        [
            InvalidArgument,
            ConfigError,
            ValidationError,
            UserNotFound,
            Unauthorized,
            InvalidAuth,
            FailedAuth,
            AuthExpired,
        ],
    )
    def test_custom_message(self, cls):
        exc = cls("custom msg")
        assert exc.message == "custom msg"

    @pytest.mark.parametrize(
        "cls",
        [
            InvalidArgument,
            ConfigError,
            ValidationError,
            UserNotFound,
            Unauthorized,
            InvalidAuth,
            FailedAuth,
            AuthExpired,
        ],
    )
    def test_default_message_is_nonempty(self, cls):
        exc = cls()
        assert exc.message  # non-empty, non-None

    def test_subclass_isinstance(self):
        exc = UserNotFound()
        assert isinstance(exc, NavException)
        assert isinstance(exc, Exception)
