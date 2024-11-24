from typing import Any
import base64
import jsonpickle
from jsonpickle.unpickler import loadclass
import cloudpickle
from datamodel import BaseModel


class ModelHandler(jsonpickle.handlers.BaseHandler):
    """ModelHandler.
    This class can handle with serializable Data Models.
    """
    def flatten(self, obj, data):
        data['__dict__'] = self.context.flatten(obj.__dict__, reset=False)
        return data

    def restore(self, obj):
        module_and_type = obj['py/object']
        mdl = loadclass(module_and_type)
        if hasattr(mdl, '__new__'):
            cls = mdl.__new__(mdl)
        else:
            cls = object.__new__(mdl)

        cls.__dict__ = self.context.restore(obj['__dict__'], reset=False)
        return cls

jsonpickle.handlers.registry.register(BaseModel, ModelHandler, base=True)


class DataSerializer:
    """DataSerializer.

    Allowing Serialize and Unserialize arbitrary python objects using JSON Pickle.
    """
    @staticmethod
    def encode(data: Any) -> str:
        """Serialize Data.
        """
        try:
            return jsonpickle.encode(data)
        except Exception as err:
            raise RuntimeError(err) from err

    @staticmethod
    def decode(data: str) -> Any:
        """Deserialize Data.
        """
        try:
            return jsonpickle.decode(data)
        except Exception as err:
            raise RuntimeError(err) from err

    @staticmethod
    def serialize(data: Any) -> bytes:
        """Serialize Data.
        """
        try:
            serialized_data = cloudpickle.dumps(data)
            encoded_data = base64.b64encode(serialized_data).decode('utf-8')
            return encoded_data
        except Exception as err:
            raise RuntimeError(err) from err

    @staticmethod
    def unserialize(data: Any) -> dict:
        """Deserialize Data.
        """
        try:
            decoded_data = base64.b64decode(data)
            return cloudpickle.loads(decoded_data)
        except Exception as err:
            raise RuntimeError(err) from err
