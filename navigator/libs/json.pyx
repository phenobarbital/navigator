# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
"""
JSON Encoder, Decoder.
"""
import uuid
import logging
from asyncpg.pgproto import pgproto
from datetime import datetime
from dataclasses import _MISSING_TYPE, MISSING
from psycopg2 import Binary  # Import Binary from psycopg2
from typing import Any, Union
from pathlib import PosixPath, PurePath, Path
from decimal import Decimal
from navigator.exceptions.exceptions cimport ValidationError
import orjson


cdef class JSONContent:
    """
    Basic Encoder using orjson
    """
    # def __init__(self, **kwargs):
    #     # eventually take into consideration when serializing
    #     self.options = kwargs
    def __call__(self, object obj, **kwargs):
        return self.encode(obj, **kwargs)

    def default(self, object obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, datetime):
            return str(obj)
        elif hasattr(obj, "isoformat"):
            return obj.isoformat()
        elif isinstance(obj, pgproto.UUID):
            return str(obj)
        elif isinstance(obj, uuid.UUID):
            return obj
        elif isinstance(obj, (PosixPath, PurePath, Path)):
            return str(obj)
        elif hasattr(obj, "hex"):
            if isinstance(obj, bytes):
                return obj.hex()
            else:
                return obj.hex
        elif hasattr(obj, 'lower'): # asyncPg Range:
            up = obj.upper
            if isinstance(up, int):
                up = up - 1  # discrete representation
            return [obj.lower, up]
        elif hasattr(obj, 'tolist'): # numpy array
            return obj.tolist()
        elif isinstance(obj, _MISSING_TYPE):
            return None
        elif obj == MISSING:
            return None
        elif isinstance(obj, Binary):  # Handle bytea column from PostgreSQL
            return str(obj)  # Convert Binary object to string
        logging.error(f'{obj!r} of Type {type(obj)} is not JSON serializable')
        raise TypeError(
            f'{obj!r} of Type {type(obj)} is not JSON serializable'
        )

    def encode(self, object obj, **kwargs) -> str:
        # decode back to str, as orjson returns bytes
        options = {
            "default": self.default,
            "option": orjson.OPT_NAIVE_UTC | orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_PASSTHROUGH_DATETIME # | orjson.OPT_NAIVE_UTC
        }
        if kwargs:
            options = {**options, **kwargs}
        try:
            return orjson.dumps(
                obj,
                **options
            ).decode('utf-8')
        except orjson.JSONEncodeError as ex:
            raise ValidationError(
                f"Invalid JSON: {ex}"
            )

    dumps = encode

    @classmethod
    def dump(cls, object obj, **kwargs):
        return cls().encode(obj, **kwargs)

    def decode(self, object obj):
        try:
            return orjson.loads(
                obj
            )
        except orjson.JSONDecodeError as ex:
            raise ValidationError(
                f"Invalid JSON data: {ex}"
            )

    loads = decode

    @classmethod
    def load(cls, object obj, **kwargs):
        return cls().decode(obj, **kwargs)


cpdef str json_encoder(object obj):
    return JSONContent().dumps(obj)

cpdef object json_decoder(object obj):
    return JSONContent().loads(obj)

cdef class BaseEncoder:
    """
    Encoder replacement for json.dumps using orjson
    """
    def __init__(self, *args, **kwargs):
        # Filter/adapt JSON arguments to ORJSON ones
        rjargs = ()
        rjkwargs = {}
        encoder = JSONContent(*rjargs, **rjkwargs)
        self.encode = encoder.__call__
