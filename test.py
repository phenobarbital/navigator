from aiohttp import web

def test(request):
    print('Handler function called')
    return web.Response(text="Hello")

async def middleware1(app, handler):
    async def middleware_handler(request):
        print('Middleware 1 called')
        response = await handler(request)
        print('Middleware 1 finished')

        return response
    return middleware_handler

async def middleware2(app, handler):
    async def middleware_handler(request):
        print('Middleware 2 called')
        response = await handler(request)
        print('Middleware 2 finished')

        return response
    return middleware_handler


app = web.Application(middlewares=[middleware1, middleware2])
app.router.add_get('/', test)
web.run_app(app, port=8181)
