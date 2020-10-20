import asyncio
import base64
import time
from datetime import datetime, timedelta

import aioredis
from aiohttp import web

# aiohttp session
from aiohttp_session import get_session, new_session
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_session.redis_storage import RedisStorage

# Storages
from cryptography import fernet

from navigator.conf import config
from navigator.libs.modules import AbstractHandler

from .backends import *
from .decorators import login_required


class AuthHandler(AbstractHandler):
    _template = """
        <!doctype html>
            <head></head>
            <body>
                <p>{message}</p>
                <form action="/login" method="POST">
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
    _backends = []

    def __init__(
        self,
        type: str = "redis",
        name: str = "AIOHTTP_SESSION",
        backends: list = [],
        **kwargs
    ):
        async def make_redis_pool(url, **kwargs):
            return await aioredis.create_pool(url, **kwargs)

        if type == "redis":
            try:
                url = kwargs["url"]
                del kwargs["url"]
            except KeyError:
                raise Exception("Error: For Redis Storage, you need session URL")
            self._pool = asyncio.get_event_loop().run_until_complete(
                make_redis_pool(url, **kwargs)
            )
            self._session_type = RedisStorage(self._pool, cookie_name=name)
        elif type == "cookie":
            try:
                secret_key = kwargs["secret_key"]
            except KeyError:
                fernet_key = fernet.Fernet.generate_key()
                secret_key = base64.urlsafe_b64decode(fernet_key)
            self._session_type = EncryptedCookieStorage(secret_key, cookie_name=name)
        # TODO: type memcached
        # configure backends
        for backend in backends:
            if backend == "hosts":
                obj = auth_hosts()
            elif backend == "session":
                obj = auth_users()
            self._backends.append(obj)

    def backends(self):
        return self._backends

    def pool(self):
        return self._pool

    async def close(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def login_page(self, request):
        username = None
        # check if authorized, instead, return to login
        session = await get_session(request)
        try:
            username = session["username"]
        except KeyError:
            template = self._template.format(message="You need to login")
        if username:
            template = self._template.format(
                message="Hello, {username}!".format(username=username)
            )
        else:
            template = self._template.format(message="You need to login")
        return web.Response(text=template, content_type="text/html")

    async def check_credentials(self, login: str = None, password: str = None):
        if login == "phenobarbital":
            return True
        return False

    async def create_session(self, request, login):
        app = request.app
        session = await new_session(request)
        session["user_id"] = login
        session["username"] = login
        last_visit = session["last_visit"] if "last_visit" in session else "Never"
        session["last_visit"] = time.time()
        session["last_visited"] = "Last visited: {}".format(last_visit)
        app["user"] = session

    async def login(self, request) -> web.Response:
        response = web.HTTPFound("/")
        form = await request.post()
        login = form.get("login")
        password = form.get("password")
        if await self.check_credentials(login, password):
            await self.create_session(request, login)
            raise response
        else:
            template = self._template.format(
                message="Invalid username/password combination"
            )
        raise web.HTTPUnauthorized(text=template, content_type="text/html")

    async def forget_user(self, request):
        session = await get_session(request)
        session.invalidate()
        try:
            app = request.app
            app["user"] = None
            request.user = None
        except Exception as err:
            print(err)

    async def logout(self, request: web.Request) -> web.Response:
        await self.forget_user(request)
        raise web.HTTPSeeOther(location="/")

    async def internal_page(self, request: web.Request) -> web.Response:
        # await check_permission(request, 'public')
        response = web.Response(body="This page is visible for all registered users")
        return response

    @login_required
    async def protected_page(self, request: web.Request) -> web.Response:
        # await check_permission(request, 'protected')
        response = web.Response(body="You are on protected page")
        return response

    def configure(self, app: web.Application) -> web.Application:
        # configure session:
        setup_session(app, self._session_type)
        router = app.router
        router.add_route("GET", "/login", self.login_page, name="index_login")
        router.add_route("POST", "/login", self.login, name="login")
        router.add_route("GET", "/logout", self.logout, name="logout")
        router.add_route("GET", "/public", self.internal_page, name="public")
        router.add_route("GET", "/protected", self.protected_page, name="protected")
        return app
