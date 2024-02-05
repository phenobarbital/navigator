import pytest
from navigator.actions.avochato import Avochato

NAME = 'PyTest Bradcast'
MESSAGE = 'Message from Pytest'
PHONE_NUMBER = '+17867516886'
MEDIA_URL = 'https://lifewaychurch.life/wp-content/uploads/2019/10/this-is-a-test-wp.png'
BROADCAST_ID = 'kgAp54xLEK'

class TestAvochato(Avochato):
    def run(self):
        pass


async def test_get_broadcast():
    async with TestAvochato() as av:
        res = await av.get_broadcasts()
        assert type(res) == dict and 'data' in res


async def test_set_broadcast():
    async with TestAvochato() as av:
        res = await av.set_broadcast(NAME, MESSAGE, PHONE_NUMBER, MEDIA_URL)
        assert type(res) == dict and 'data' in res


async def test_update_broadcast():
    
    async with TestAvochato() as av:
        res = await av.update_broadcast(BROADCAST_ID, NAME, MESSAGE, PHONE_NUMBER, MEDIA_URL)
        assert type(res) == dict and 'data' in res


async def test_publish_broadcast():
    async with TestAvochato() as av:
        res = await av.publish_broadcast(BROADCAST_ID)
        assert type(res) == dict and 'data' in res


async def test_get_messages():
    async with TestAvochato() as av:
        res = await av.get_messages()
        assert type(res) == dict and 'data' in res


async def test_publish_message():
    async with TestAvochato() as av:
        res = await av.send_message(PHONE_NUMBER, MESSAGE, PHONE_NUMBER, MEDIA_URL)
        assert type(res) == dict and 'data' in res
