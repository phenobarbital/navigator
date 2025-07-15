from aiohttp import web
from navconfig.logging import logging
from navigator_auth import AuthHandler
from navigator import Application
from navigator.responses import HTMLResponse


# Middleware to print request details
@web.middleware
async def debug_middleware(request, handler):
    app = request.app
    for route in app.router.routes():
        logging.debug(
            f"Route added: {route.resource}, method: {route.method}, Path: {route.resource.canonical}"
        )
    logging.debug(
        f"Request received: {request.method} {request.path}"
    )
    match_info = request.match_info
    logging.debug(f"Matched info: {match_info}")
    response = await handler(request)
    return response

app = Application(
    middlewares=[debug_middleware]
)

auth = AuthHandler()
auth.setup(app)  # configure this Auth system into App.

@app.get('/')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(body="Hola Mundo")


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        pass
