#!/usr/bin/env python3
# import asyncio
from aiohttp import web
from app import Main
from navigator import Application
from navigator.responses import JSONResponse #, sse_response
from navigator.ext.memcache import Memcache
from navigator.ext.locale import LocaleSupport

# define a new Application
app = Application(Main, enable_jinja2=True)
# app = Application()
mcache = Memcache()
mcache.setup(app)

# support localization:
l18n = LocaleSupport(localization=['en_US', 'es_ES', 'it_IT', 'de_DE'], domain='nav')
l18n.setup(app)

# Enable WebSockets Support
app.add_websockets()

@app.get('/hola')
async def hola(request: web.Request) -> web.Response:
    try:
        print('CORRE ---')
        ## accessing memcache connector:
        m = app['memcache']
        await m.set('Salute', 'Hello')
        print(f"Salute: {await m.get('Salute')}")
        ## accessing Redis connector:
        # redis = app['redis']
        # await redis.set('salute', 'Hola')
        # d = await redis.get('salute')
        # print(f'Saludo {d}')
    finally:
        pass
    try:
        locale = app['locale']
        print('CURRENT LOCALE : ', locale.current_locale())
        it = locale.translator(lang='it')
        es = locale.translator(lang='es')
        de = locale.translator(lang='de')
        message = {
            "en": _('helloworld'), # default translator,
            "es": es('helloworld'),
            "it": it('helloworld'),
            "de": de('helloworld')
        }
    except Exception as err:
        print(err)
    return JSONResponse(message)

@app.get('/template')
async def test_template(request: web.Request) -> web.Response:
    view = request.app['template'].view
    return await view('home.html', {"number": 42})

# Using the Application Context
@app.get('/sample')
@app.template('tmpl.jinja2', content_type='application/json')
def handler(request: web.Request) -> web.Response:
    return {'name': 'Jesus', 'surname': 'Lara'}

# async def hello_server(request):
#     # create a SSE response object
#     async with sse_response(request, headers={"X-SSE": "navigator", "Connection": "keep-alive"}) as resp:
#         resp.ping_interval = 1
#         while True:
#             data = 'Server Time : {}'.format(datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
#             print(data)
#             await resp.send(data)
#             await asyncio.sleep(1)
#     return resp
# app.router.add_route('GET', '/hello_server', hello_server)

# @app.get('/time_server')
# async def index(request):
#     d = """
#         <html>
#         <body>
#             <script>
#                 var evtSource = new EventSource("//navigator-dev.dev.local:5000/hello_server", { withCredentials: true });
#                 evtSource.onmessage = function(e) {
#                     document.getElementById('response').innerText = e.data
#                 }
#                 evtSource.addEventListener("ping", function(event) {
#                     const newElement = document.createElement("li");
#                     const eventList = document.getElementById("list");
#                     const time = JSON.parse(event.data).time;
#                     newElement.textContent = "ping at " + time;
#                     eventList.appendChild(newElement);
#                 });
#                 evtSource.onerror = function(err) {
#                     console.error("EventSource failed:", err);
#                 };
#             </script>
#             <h1>Response from server:</h1>
#             <div id="response"></div>
#         </body>
#     </html>
#     """
#     return Response(text=d, content_type='text/html')

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
