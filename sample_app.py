from aiohttp import web
from navigator import Application
from navigator.responses import HTMLResponse


app = Application()


@app.get('/')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(body="Hola Mundo")


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        pass
