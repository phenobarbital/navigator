from aiohttp import web
from navigator_auth.decorators import (
    is_authenticated,
    user_session
)
from navigator_auth import AuthHandler
from navigator.views import BaseView
from navigator import Application
from navigator.responses import HTMLResponse


@is_authenticated()
@user_session()
class ChatHandler(BaseView):
    """
    ChatHandler.
    description: ChatHandler for Parrot Application.
    """

    async def get(self, **kwargs):
        """
        get.
        description: Get method for ChatHandler.
        """
        name = self.request.match_info.get('chatbot_name', None)
        if not name:
            return self.json_response({
                "message": "Welcome to Parrot Chatbot Service."
            })
        return self.json_response({
            "message": f"Hello {name}."
        })

@is_authenticated()
@user_session()
class BotHandler(BaseView):
    """BotHandler.


    Use this handler to interact with a brand new chatbot, consuming a configuration.
    """
    async def put(self):
        """Create a New Bot (passing a configuration).
        """
        return self.json_response({
            "message": "Welcome to Parrot Chatbot Service."
        })

app = Application()

@app.get('/hello')
async def hola(request: web.Request) -> web.Response:
    return HTMLResponse(content="<h1>Hello Airport</h1>")

# BotHandler.setup(app, r'/api/v1/bots')
ChatHandler.setup(app, r'/api/v1/chat/{chatbot_name}')

app.router.add_view(r'/api/v1/bots', BotHandler)

session = AuthHandler()
session.setup(app)

if __name__ == "__main__":
    try:
        app.run()
    except KeyboardInterrupt:
        pass
