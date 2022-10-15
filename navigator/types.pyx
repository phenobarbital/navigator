# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
from libcpp cimport bool
from typing import Tuple, Callable, Awaitable
from urllib.parse import urlparse, parse_qs, ParseResult
from aiohttp import web
from navconfig import config, DEBUG
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
    cdef str value
    cdef str scheme
    cdef str path
    cdef str host
    cdef str port
    cdef str netloc
    cdef str query
    cdef str fragment
    cdef dict params
    cdef bool is_absolute

    def __cinit__(self):
        self.is_absolute = False

    def __init__(self, str value):
        try:
            parsed = urlparse(value)
        except (AttributeError, ValueError):
            raise ValidationError(
                f'Address cannot be parsed as URL ({value})'
            )
        # components
        self.value = value
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port
        self.netloc = parsed.netloc
        self.path = parsed.path
        self.query = parsed.query
        self.fragment = parsed.fragment
        self.is_absolute = (self.scheme is not None)
        try:
            self.params = parse_qs(self.query)
        except:
            pass

    def __repr__(self):
        return f'<URL: {self.value}>'

    def __str__(self):
        return self.value

    @property
    def host(self) -> str:
        return self.host

    @property
    def port(self) -> str:
        return self.port

    @property
    def qs_params(self) -> str:
        return self.params

    @property
    def scheme(self) -> str:
        return self.scheme

    @property
    def netloc(self) -> str:
        return self.netloc

    def __getattribute__(self, name):
        try:
            value = super(URL, self).__getattribute__(name)
            return value
        except AttributeError as ae:
            return None

    cpdef URL change_scheme(self, str scheme):
        if scheme in ('http', 'https', 'ftp', 'ssh', 's3', 'webdav'):
            if self.is_absolute is True:
                return URL(scheme + self.value[len(self.scheme):])
            else:
                raise TypeError(
                    "Cannot Generate a URL from a Partial URL."
                )
        else:
            raise ValueError(
                f'Invalid type of scheme: {scheme}'
            )

    cpdef URL change_host(self, str host):
        if self.is_absolute is False:
            raise TypeError(
                "Cannot Generate a URL from a Partial URL."
            )
        else:
            fragment = f"#{self.fragment}" if self.fragment else ''
            query = f"?{self.query}" if self.query else ''
            port = f":{self.port}" if self.port else ''
            return URL(f"{self.scheme}://{host}{port}{self.path}{self.query}{self.fragment}")

    def __eq__(self, str url):
        if isinstance(url, URL):
            return self.value == url.value
        else:
            return str(url) == url.value
