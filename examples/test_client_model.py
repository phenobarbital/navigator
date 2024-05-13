import aiohttp
import asyncio
import json
from navigator.conf import APP_HOST, APP_PORT

async def test_validate_payload():
    url = f'http://{APP_HOST}:{APP_PORT}/api/v1/animal'
    headers = {'Content-Type': 'application/json'}

    payload = {
        "Lion": {"name": "Lion", "specie": "Panthera leo", "age": 5},
        "Elephant": {"name": "Elephant", "habitat": "Savannah", "is_wild": True},
        "Snake": {"name": "Snake", "specie": "Reptilia", "age": 2}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                response_data = await response.json()
            else:
                response_data = await response.text()
            print(f"Status: {response.status}")
            print(f"Response: {response_data}")

if __name__ == '__main__':
    asyncio.run(test_validate_payload())
