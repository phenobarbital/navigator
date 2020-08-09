import asyncio
from aiohttp import web
from navigator.libs.modules import AbstractHandler
# aiohttp session
from aiohttp_session import get_session, setup as setup_session
# Storages
from cryptography import fernet
import base64
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_session.redis_storage import RedisStorage
import aioredis

from navigator.conf import config

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
    _session_type = None
    _pool = None

    def __init__(self, type: str = 'redis', name:str = 'AIOHTTP_SESSION', **kwargs):
        async def make_redis_pool(url, **kwargs):
            return await aioredis.create_pool(url, **kwargs)
        if type == 'redis':
            try:
                url = kwargs['url']
                del kwargs['url']
            except KeyError:
                raise Exception("Error: For Redis Storage, you need session URL")
            self._pool = asyncio.get_event_loop().run_until_complete(make_redis_pool(url, **kwargs))
            self._session_type = RedisStorage(
                self._pool, cookie_name=name
            )
        elif type == 'cookie':
            try:
                secret_key = kwargs['secret_key']
            except KeyError:
                fernet_key = fernet.Fernet.generate_key()
                secret_key = base64.urlsafe_b64decode(fernet_key)
            self._session_type = EncryptedCookieStorage(secret_key, cookie_name=name)

    def pool(self):
        return self._pool

    async def close(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

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

    def configure(self, app: web.Application) -> web.Application:
        # configure session:
        setup_session(app, self._session_type)
        router = app.router
        router.add_route('GET', '/login', self.index, name='index_login')
        router.add_route('POST', '/login', self.login, name='login')
        router.add_route('GET', '/logout', self.logout, name='logout')
        router.add_route('GET', '/public', self.internal_page, name='public')
        router.add_route('GET', '/protected', self.protected_page, name='protected')
        return app
