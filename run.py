#!/usr/bin/env python3
import asyncio
import logging
from app import Main
from aiohttp import web
from navigator import Application, Response
from navigator.responses import EventSourceResponse, sse_response
from datetime import datetime


# define new Application
app = Application(app=Main)

# Enable WebSockets Support
app.add_websockets()

@app.get('/hola')
async def hola(request: web.Request, *args, **kwargs) -> web.Response:
    try:
        print('HOLA MUNDO')
        print('USER: ', request.user)
        print(request.get('session'))
    except Exception as err:
        print(err)
    return Response('Hola Mundo')

async def hello_server(request):
    # create a SSE response object
    async with sse_response(request, headers={"X-SSE": "navigator", "Connection": "keep-alive"}) as resp:
        resp.ping_interval = 1
        while True:
            data = 'Server Time : {}'.format(datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
            print(data)
            await resp.send(data)
            await asyncio.sleep(1)
    return resp
app.router.add_route('GET', '/hello_server', hello_server)

@app.get('/time_server')
async def index(request):
    d = """
        <html>
        <body>
            <script>
                var evtSource = new EventSource("//navigator-dev.dev.local:5000/hello_server", { withCredentials: true });
                evtSource.onmessage = function(e) {
                    document.getElementById('response').innerText = e.data
                }
                evtSource.addEventListener("ping", function(event) {
                    const newElement = document.createElement("li");
                    const eventList = document.getElementById("list");
                    const time = JSON.parse(event.data).time;
                    newElement.textContent = "ping at " + time;
                    eventList.appendChild(newElement);
                });
                evtSource.onerror = function(err) {
                    console.error("EventSource failed:", err);
                };
            </script>
            <h1>Response from server:</h1>
            <div id="response"></div>
        </body>
    </html>
    """
    return Response(text=d, content_type='text/html')

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
