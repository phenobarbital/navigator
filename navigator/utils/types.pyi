# Copyright (C) 2018-present Jesus Lara
#
"""Python type stub for ``navigator/utils/types.pyx``.

Spec FEAT-001 / TASK-006 — surfaces the :class:`Singleton` metaclass
to static type checkers so callers that do
``class MyConfig(metaclass=Singleton): ...`` get IDE autocompletion
and mypy coverage without having to introspect the compiled ``.so``.
"""
from typing import Any, Dict


class Singleton(type):
    """Metaclass that caches a single instance per derived class.

    ``Singleton`` tracks created instances on the metaclass-level
    ``_instances`` dict; subsequent calls return the cached instance.
    """

    _instances: Dict[type, Any]

    def __call__(cls, *args: Any, **kwargs: Any) -> Any: ...
