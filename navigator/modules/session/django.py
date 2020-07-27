import base64
from navigator.conf import SESSION_PREFIX
from navigator.modules.session.session import AbstractSession
from typing import Any

class djangoSession(AbstractSession):

        async def decode(self, key):
            try:
                result = await self._backend.get('{}:{}'.format(SESSION_PREFIX, key))
                data = base64.b64decode(result)
                session_data = data.decode('utf-8').split(':', 1)
                self._session_key = key
                self._session_id = session_data[0]
                if session_data:
                    self._result = json.loads(session_data[1])
                return self
            except Exception as err:
                print(err)
                return None

        async def encode(self, key, data):
            raise NotImplementedError
