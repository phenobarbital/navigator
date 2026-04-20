# Copyright (C) 2018-present Jesus Lara
#
"""Python type stub for ``navigator/types.pyx``.

Spec FEAT-001 / TASK-006 — allows IDEs and static type checkers (mypy,
pyright) to understand the public surface of the compiled Cython module
without having to parse the ``.pyx`` source or poke at the compiled
``.so`` symbols.
"""
from typing import Any, Awaitable, Callable, Dict, Tuple

from aiohttp import web


# --- Type aliases re-exported from types.pyx ---------------------------------

WebApp = web.Application
HTTPMethod = str
HTTPLocation = str
HTTPRequest = web.Request
HTTPResponse = web.StreamResponse
HTTPHandler = Callable[[HTTPRequest], Awaitable[HTTPResponse]]
HTTPRoute = Tuple[HTTPMethod, HTTPLocation, HTTPHandler]


class URL:
    """Lightweight URL wrapper (Cython cdef class).

    All attributes are exposed as Python-level instance state. The class
    overrides ``__getattribute__`` to return ``None`` for missing
    attributes instead of raising :class:`AttributeError`.
    """

    value: str
    scheme: str
    path: str
    host: str
    port: str
    netloc: str
    query: str
    fragment: str
    params: Dict[str, Any]
    is_absolute: bool

    def __init__(self, value: str) -> None: ...

    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...
    def __eq__(self, url: object) -> bool: ...  # type: ignore[override]

    @property
    def qs_params(self) -> Dict[str, Any]: ...

    def change_scheme(self, scheme: str) -> "URL": ...
    def change_host(self, host: str) -> "URL": ...
