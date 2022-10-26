"""
JSON Encoder, Decoder.
"""
from asyncpg.pgproto import pgproto
from dataclasses import _MISSING_TYPE, MISSING
from typing import Any, Union
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
        elif hasattr(obj, "isoformat"):
            return obj.isoformat()
        elif isinstance(obj, pgproto.UUID):
            return str(obj)
        elif hasattr(obj, "hex"):
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
        raise TypeError(f"{obj!r} is not JSON serializable")

    def encode(self, object obj, **kwargs) -> str:
        # decode back to str, as orjson returns bytes
        options = {
            "default": self.default,
            "option": orjson.OPT_NAIVE_UTC | orjson.OPT_SERIALIZE_NUMPY| orjson.OPT_UTC_Z
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
                f"Invalid JSON data: {ex}"
            )

    dumps = encode

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


cpdef str json_encoder(object obj):
    return JSONContent().dumps(obj)

cpdef object json_decoder(object obj):
    return JSONContent().loads(obj)
