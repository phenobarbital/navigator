from aiohttp import web
from navigator import Application
from app import Main


async def handle(request):
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    return web.Response(text=text)

app = Application(app=Main)

app.add_routes([web.get('/', handle),
                web.get('/{name}', handle)])



if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
