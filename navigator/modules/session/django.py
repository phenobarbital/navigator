import base64
from typing import Any

from navigator.conf import SESSION_PREFIX
from navigator.modules.session.session import AbstractSession

try:
    import ujson as json
except ImportError:
    import json


class djangoSession(AbstractSession):
    async def decode(self, key: str = None):
        try:
            result = await self._backend.get("{}:{}".format(SESSION_PREFIX, key))
            if result:
                data = base64.b64decode(result)
                session_data = data.decode("utf-8").split(":", 1)
                self._session_key = key
                self._session_id = session_data[0]
                if session_data:
                    r = json.loads(session_data[1])
                    self._parent.set_result(r)
                    self._parent.id(self._session_id)
                    return True
            else:
                return False
        except Exception as err:
            print(err)
            logging.debug("Decoding Error: {}".format(err))
            return False

    async def encode(self, key, data):
        raise NotImplementedError
