import decimal
import json
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

import asyncpg


class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return str(obj)
        else:
            return str(object=obj)
        return json.JSONEncoder.default(self, obj)


class IntRangeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, asyncpg.Range):
            up = obj.upper
            if isinstance(obj.upper, int):
                up = obj.upper - 1  # discrete representation
            return [obj.lower, up]
        else:
            return str(object=obj)
        return json.JSONEncoder.default(self, obj)


class DefaultEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "hex"):
            return obj.hex
        elif isinstance(obj, Enum):
            if not obj.value:
                return None
            else:
                return str(obj.value)
        elif isinstance(obj, uuid.UUID):
            try:
                return str(obj)
            except Exception as e:
                return obj.hex
        elif isinstance(obj, decimal.Decimal):
            return float(obj)
        elif isinstance(obj, Decimal):
            return str(obj)
        elif hasattr(obj, "isoformat"):
            return obj.isoformat()
        elif isinstance(obj, asyncpg.Range):
            return [obj.lower, obj.upper]
        else:
            return str(object=obj)
        return json.JSONEncoder.default(self, obj)
