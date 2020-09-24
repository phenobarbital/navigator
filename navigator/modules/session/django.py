import base64
from navigator.conf import SESSION_PREFIX
from navigator.modules.session.session import AbstractSession
from typing import Any
try:
    import ujson as json
except ImportError:
    import json

class djangoSession(AbstractSession):

        async def decode(self, key: str =None):
            try:
                print(SESSION_PREFIX, key)
                result = await self._backend.get('{}:{}'.format(SESSION_PREFIX, key))
                data = base64.b64decode(result)
                session_data = data.decode('utf-8').split(':', 1)
                print(session_data)
                self._session_key = key
                self._session_id = session_data[0]
                if session_data:
                    r = json.loads(session_data[1])
                    self._parent.set_result(r)
                    self._parent.id(self._session_id)
            except Exception as err:
                print(err)
                logging.debug('Decoding Error: {}'.format(err))
            finally:
                return self._parent

        async def encode(self, key, data):
            raise NotImplementedError
