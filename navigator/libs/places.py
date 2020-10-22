import asyncio

import uvloop
from aiogmaps import Client

# make asyncio use the event loop provided by uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def get_places(client_id: str, secret: str, place_id: str):
    loop = asyncio.get_event_loop()
    async with Client(client_id=client_id, client_secret=secret, loop=loop) as client:
        return await client.place(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")
