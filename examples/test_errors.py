from aiohttp import web
from navigator import Application
from navigator.views import BaseHandler

class myHand(BaseHandler):
    async def my_first(self, request):
        name = request.match_info.get('name', "Anonymous")
        text = "Hello, " + name
        return self.response(
            response=text,
            status=403,
            content_type='text/html'
        )
        # return self.error(
        #     response={"error": "To de Moon"},
        #     status=400,
        #     content_type='text/html'
        # )
        # return self.critical(
        #     reason={"error": "To de Moon"},
        #     status=500,
        #     content_type='text/html'
        # )
        # return self.not_allowed(request=request, allowed=['POST', 'PUT'])
        # return self.not_implemented('No Implementado')

app = Application()

handle = myHand()
app.add_routes([web.get('/', handle.my_first),
                web.get('/{name}', handle.my_first)])


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
