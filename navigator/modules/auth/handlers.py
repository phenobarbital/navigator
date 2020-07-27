from aiohttp import web
from navigator.libs.modules import AbstractHandler
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from navigator.conf import config, SECRET_KEY

class AuthHandler(AbstractHandler):
    _template = """
        <!doctype html>
            <head></head>
            <body>
                <p>{message}</p>
                <form action="/login" method="post">
                  Login:
                  <input type="text" name="login">
                  Password:
                  <input type="password" name="password">
                  <input type="submit" value="Login">
                </form>
                <a href="/logout">Logout</a>
            </body>
    """

    async def index(self, request):
        response = web.HTTPFound('/')
        # check if authorized, instead, return to login
        username = 'phenobarbital'
        if username:
            template = self._template.format(message='Hello, {username}!'.format(username=username))
        else:
            template = self._template.format(message='You need to login')
        return web.Response(text=template, content_type='text/html')

    async def login(self, request) -> web.Response:
        response = web.HTTPFound('/')
        form = await request.post()
        login = form.get('login')
        password = form.get('password')
        # db_engine = request.app.db_engine
        # if await check_credentials(db_engine, login, password):
        #     await remember(request, response, login)
        #     raise response
        raise web.HTTPUnauthorized(
            body='Invalid username/password combination')

    async def logout(self, request):
        #await check_authorized(request)
        response = web.Response(body='You have been logged out')
        #await forget(request, response)
        return response

    async def internal_page(self, request: web.Request) -> web.Response:
        #await check_permission(request, 'public')
        response = web.Response(
            body='This page is visible for all registered users')
        return response

    async def protected_page(self, request: web.Request) -> web.Response:
        #await check_permission(request, 'protected')
        response = web.Response(body='You are on protected page')
        return response

    def configure(self, app: web.Application) -> None:
        # configure session:
        setup_session(app, EncryptedCookieStorage(SECRET_KEY))
        router = app.router
        router.add_route('GET', '/login', self.index, name='index_login')
        router.add_route('POST', '/login', self.login, name='login')
        router.add_route('GET', '/logout', self.logout, name='logout')
        router.add_route('GET', '/public', self.internal_page, name='public')
        router.add_route('GET', '/protected', self.protected_page, name='protected')
