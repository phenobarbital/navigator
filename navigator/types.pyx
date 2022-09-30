# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
import httptools
from httptools.parser import errors

from typing import Tuple, Callable, Awaitable
from urllib.parse import urlparse, parse_qs, ParseResult
from aiohttp import web
from navigator.exceptions.exceptions import ValidationError

# Useful types:
WebApp = web.Application
HTTPMethod = str
HTTPLocation = str
HTTPRequest = web.Request
HTTPResponse = web.StreamResponse
HTTPHandler = Callable[[HTTPRequest], Awaitable[HTTPResponse]]

HTTPRoute = Tuple[
    HTTPMethod,
    HTTPLocation,
    HTTPHandler,
]

## URL definition
cdef class URL:
    def __init__(self, str value):
        try:
            parsed = urlparse(value)
        except (AttributeError, ValueError):
            raise ValidationError(
                f'Address cannot be parsed as URL ({value})'
            )
        # components
        self.value = value
        self.schema = parsed.schema
        self.host = parsed.hostname
        self.port = int(parsed.port)
        self.netloc = parsed.netloc
        self.query = parsed.query
        self.fragment = parsed.fragment
        self.is_absolute = (self.schema is not None)
        try:
            self.params = parse_qs(self.query)
        except:
            pass



    def __repr__(self):
        return f'<URL: {self.address}>'

    def __str__(self):
        return self.address
