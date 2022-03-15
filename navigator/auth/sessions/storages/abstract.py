"""Base Class for all Session Storages."""

import abc
import json
import uuid
import time
import asyncio
import logging
from aiohttp import web
from aiohttp.web_middlewares import Handler, middleware
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Iterator,
    Mapping,
    MutableMapping,
    Optional
)
from navigator.conf import (
    SESSION_NAME,
    SESSION_PREFIX,
    SESSION_TIMEOUT,
    SESSION_KEY,
    SESSION_OBJECT,
    SESSION_STORAGE
)
from jsonpickle.unpickler import loadclass
import jsonpickle
from asyncdb.models import Model

class ModelHandler(jsonpickle.handlers.BaseHandler):
    def flatten(self, obj, data):
        data['__dict__'] = self.context.flatten(obj.__dict__, reset=False)
        return data
    
    def restore(self, data):
        module_and_type = data['py/object']
        cls = loadclass(module_and_type)
        if hasattr(cls, '__new__'):
            obj = cls.__new__(cls)
        else:
            obj = object.__new__(cls)

        obj.__dict__ = self.context.restore(data['__dict__'], reset=False)
        return obj
        
jsonpickle.handlers.registry.register(Model, ModelHandler)

class SessionData(MutableMapping[str, Any]):
    """Session dict-like object.

    TODO: Support saving directly into Storage.
    """

    _data: Dict[str, Any] = {}
    _db: Callable = None

    def __init__(
        self,
        db: Callable, *,
        data: Optional[Mapping[str, Any]] = {},
        new: bool = False,
        identity: Optional[Any] = None,
        max_age: Optional[int] = None
    ) -> None:
        self._changed = False
        self._data = {}
        self._db = db
        self._identity = data.get(SESSION_KEY, None) if data else identity
        if not self._identity:
            self._identity = uuid.uuid4().hex
        self._new = new if data != {} else True
        self._max_age = max_age if max_age else None
        created = data.get('created', None) if data else None
        now = int(time.time())
        age = now - created if created else now
        if max_age is not None and age > max_age:
            session_data = None
        if self._new or created is None:
            self._created = now
        else:
            self._created = created

        if data is not None:
            self._data.update(data)

    def __repr__(self) -> str:
        return '<{} [new:{}, created:{}] {!r}>'.format(
            'NAV-Session ', self.new, self.created, self._data
        )

    @property
    def new(self) -> bool:
        return self._new

    @property
    def identity(self) -> Optional[Any]:  # type: ignore[misc]
        return self._identity

    @property
    def created(self) -> int:
        return self._created

    @property
    def empty(self) -> bool:
        return not bool(self._data)

    @property
    def max_age(self) -> Optional[int]:
        return self._max_age

    @max_age.setter
    def max_age(self, value: Optional[int]) -> None:
        self._max_age = value

    @property
    def is_changed(self) -> bool:
        return self._changed

    def changed(self) -> None:
        self._changed = True

    def session_data(self) -> Dict:
        return self._data

    def invalidate(self) -> None:
        self._changed = True
        self._data = {}

    # Magic Methods
    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._changed = True
        # TODO: also, saved into redis automatically

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._changed = True

    def __getattr__(self, key: str) -> Any:
        return self._data[key]
    
    def encode(self, obj: Any) -> str:
        """encode

            Encode an object using jsonpickle.
        Args:
            obj (Any): Object to be encoded using jsonpickle

        Raises:
            RuntimeError: Error converting data to json.

        Returns:
            str: json version of the data
        """
        try:
            return jsonpickle.encode(obj)
        except Exception as err:
            raise RuntimeError(err)
    
    def decode(self, key: str) -> Any:
        """decode.

            Decoding a Session Key using jsonpickle.
        Args:
            key (str): key name.

        Raises:
            RuntimeError: Error converting data from json.

        Returns:
            Any: object converted.
        """
        try:
            print('AQUI ==================')
            value = self._data[key]
            return jsonpickle.decode(value)
        except Exception as err:
            raise RuntimeError(err)
        finally:
            print('Y AQUI ===========')


class AbstractStorage(metaclass=abc.ABCMeta):

    def id_factory(self) -> str:
        return uuid.uuid4().hex

    def __init__(self, max_age: int = None, secure: bool = None) -> None:
        if not max_age:
            self.max_age = SESSION_TIMEOUT
        else:
            self.max_age = max_age

    def configure_session(self, app: web.Application) -> None:
        """Configure the Middleware for NAV Session."""
        app.middlewares.append(
            session_middleware(app, self)
        )

    @abc.abstractmethod
    async def new_session(
        self,
        request: web.Request,
        data: Dict = None
    ) -> SessionData:
        pass

    @abc.abstractmethod
    async def load_session(
        self,
        request: web.Request,
        new: bool = False
    ) -> SessionData:
        pass

    @abc.abstractmethod
    async def get_session(self, request: web.Request) -> SessionData:
        pass

    @abc.abstractmethod
    async def save_session(self,
        request: web.Request,
        response: web.StreamResponse,
        session: SessionData
    ) -> None:
        pass

    @abc.abstractmethod
    async def invalidate(
        self,
        request: web.Request,
        session: SessionData
    ) -> None:
        """Try to Invalidate the Session in the Storage."""
        pass

    async def forgot(self, request):
        """Delete a User Session."""
        session = await self.get_session(request)
        await self.invalidate(request, session)
        request["session"] = None
        try:
            del request[SESSION_KEY]
            del request[SESSION_OBJECT]
        except Exception as err:
            print('Error: ', err)
        finally:
            return True

"""
 Basic Middleware for Session System
"""
def session_middleware(
        app: web.Application,
        storage: 'AbstractStorage'
) -> middleware:
    """Middleware to attach Session Storage to every Request."""
    if not isinstance(storage, AbstractStorage):
        raise RuntimeError(f"Expected an AbstractStorage got {storage!s}")

    @web.middleware
    async def middleware(
            request: web.Request,
            handler: Handler
    ) -> web.StreamResponse:
        request[SESSION_STORAGE] = storage
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            raise exc
        if not isinstance(response, (web.StreamResponse, web.HTTPException)):
            # likely got websocket or streaming
            return response
        if response.prepared:
            raise RuntimeError(
                "We Cannot save session data into on prepared responses"
            )
        session = request.get(SESSION_OBJECT)
        if isinstance(session, SessionData):
            if session.is_changed:
                await storage.save_session(request, response, session)
        return response

    return middleware
