#!/usr/bin/env python3
import sys
import ssl
import signal
import asyncio
import inspect
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from typing import (
    Any,
    Union
)
from importlib import import_module
from collections.abc import Callable
from dataclasses import dataclass
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web_exceptions import HTTPError
import sockjs
import aiohttp_cors
from navconfig import config
from navconfig.logging import logging
from navigator.applications import BaseHandler
from navigator.types import BaseApplication
from navigator.functions import cPrint
from navigator.exceptions import (
    NavException,
    ConfigError,
    InvalidArgument
)
# Exception Handlers
from navigator.exceptions.handlers import (
    nav_exception_handler,
    shutdown
)
# Template Extension.
from navigator.template import TemplateParser
# websocket resources
from navigator.resources import WebSocket, channel_handler
from navigator.utils.functions import get_logger
from navigator.libs.json import json_encoder
from .apps import ApplicationInstaller


if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec
P = ParamSpec("P")


class Application(BaseApplication):
    """Application.

        Main class for Navigator Application.
    Args:
        object (_type_): _description_
    """
    def __init__(
        self, # pylint: disable=W0613
        *args: P.args,
        app: BaseHandler = None,
        title: str = '',
        description: str = 'NAVIGATOR APP',
        contact: str = '',
        enable_jinja2: bool = False,
        template_dirs: list = None,
        **kwargs: P.kwargs
    ) -> None:
        super(
            Application, self
        ).__init__(
            *args,
            title=title,
            contact=contact,
            description=description,
            **kwargs
        )
        # getting the application Logger
        self._logger = get_logger(self.title)
        if self.debug is False:
            # also, disable logging for 'aiohttp.access'
            aio = logging.getLogger('aiohttp.access')
            aio.setLevel(logging.CRITICAL)
        # template parser
        self.enable_jinja2 = enable_jinja2
        self.template_dirs = template_dirs
        # configuring asyncio loop
        try:
            self._loop = asyncio.new_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
        self._loop.set_exception_handler(nav_exception_handler)
        asyncio.set_event_loop(self._loop)
        # May want to catch other signals too
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            self._loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(
                    shutdown(self._loop, s)
                )
            )
        from navigator.conf import Context # pylint: disable=C0415
        # here:
        if not app:
            default_app = config.get('default_app', fallback='AppHandler')
            try:
                cls = import_module('navigator.applications.types', package=default_app)
                app_obj = getattr(cls, default_app)
                # create an instance of AppHandler
                self.app = app_obj(Context, evt=self._loop, **kwargs)
            except ImportError as ex:
                raise NavException(
                    f"Cannot Import default App class {default_app}: {ex}"
                ) from ex
        else:
            self.app = app(Context, evt=self._loop, **kwargs)

    def active_extensions(self) -> list:
        return self.app.App.extensions.keys()

    def setup_app(self) -> web.Application:
        app = self.get_app()
        if self.enable_jinja2 is True:
            try:
                # TODO: passing more parameters via configuration.
                parser = TemplateParser(
                    template_dir=self.template_dirs
                )
                parser.setup(app)
            except Exception as e:
                logging.exception(e)
                raise ConfigError(
                    f"Error on Template configuration, {e}"
                ) from e
        # setup The Application and Sub-Applications Startup
        installer = ApplicationInstaller()
        INSTALLED_APPS: list = installer.installed_apps()
        # load dynamically the app Startup:
        try:
            app_init = config.get('APP_STARTUP', fallback='navigator.applications.startup')
            cls = import_module(
                app_init, package='app_startup'
            )
            app_startup = getattr(cls, 'app_startup')
            app_startup(INSTALLED_APPS, app, context=app['config'])
        except ImportError as ex:
            raise NavException(
                f"Exception: Can't load Application Startup: {app_init}"
            ) from ex
        # Configure Routes
        self.app.configure()
        cors = aiohttp_cors.setup(
            app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_methods="*",
                    allow_headers="*",
                    max_age=3600,
                )
            },
        )
        self.app.setup_cors(cors)
        self.app.setup_docs()
        return app

    def add_websockets(self) -> None:
        """
        add_websockets.
        description: enable support for websockets in the main App
        """
        app = self.get_app()
        if self.debug:
            logging.debug(":: Enabling WebSockets ::")
        # websockets
        app.router.add_route("GET", "/ws", WebSocket)
        # websocket channels
        app.router.add_route("GET", "/ws/{channel}", channel_handler)

    def add_routes(self, routes: list) -> None:
        """
        add_routes
        description: append a list of routes to routes dict
        """
        # TODO: avoid to add same route different times
        try:
            self.get_app().add_routes(routes)
        except Exception as ex:
            raise NavException(
                f"Error adding routes: {ex}"
            ) from ex

    def add_route(self, method: str = 'GET', route: str = None, fn: Callable = None) -> None:
        """add_route.

        Args:
            method (str, optional): http method. Defaults to 'GET'.
            route (str, optional): path. Defaults to None.
            fn (Callable, optional): function callable. Defaults to None.
        """
        self.get_app().router.add_route(method, route, fn)

    def add_static(self, route: str, path: str):
        """
        add_static
        description: register new route to static path.
        """
        self.get_app().add_static(route, path)

    def add_view(self, route: str, handler: Any):
        self.get_app().router.add_view(route, handler)

    def threaded_func(self, func: Callable, threaded: bool = False):
        @wraps(func)
        async def _wrap(request):
            result = None
            try:
                if threaded:

                    def blocking_function():
                        return asyncio.new_event_loop().run_until_complete(
                            func(request)
                        )

                    result = await self._loop.run_in_executor(
                        ThreadPoolExecutor(max_workers=1), blocking_function
                    )
                else:
                    result = await func(request)
                return result
            except (ValueError, RuntimeError) as err:
                self._logger.exception(err)
                raise InvalidArgument(
                    f"Error running Threaded Function: {err}"
                ) from err
        return _wrap

    def route(self, route: str, method: str = "GET", threaded: bool = False):
        """
        route.
        description: decorator for register a new HTTP route.
        """

        def _decorator(func):
            self.app.App.router.add_route(
                method, route, self.threaded_func(func, threaded)
            )
            return func

        return _decorator

    def add_get(self, route: str, threaded: bool = False) -> Callable:
        def _decorator(func):
            self.app.App.router.add_get(
                route, self.threaded_func(func, threaded), allow_head=False
            )
            return func

        return _decorator

    def Response(self, content: Any) -> web.Response:
        return web.Response(text=content)

    def get(self, route: str):
        def _decorator(func):
            self.app.App.router.add_get(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self._logger.exception(err)
                    raise ConfigError(
                        f"Error configuring GET Route {route}: {err}"
                    ) from err
            return _wrap

        return _decorator

    @property
    def router(self):
        return self.app.App.router

    def post(self, route: str):
        def _decorator(func):
            self.app.App.router.add_post(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self._logger.exception(err)
                    raise ConfigError(
                        f"Error configuring POST Route {route}: {err}"
                    ) from err

            return _wrap
        return _decorator

    def template(
            self,
            template: str,
            content_type: str = 'text/html',
            encoding: str = "utf-8",
            status: int = 200,
            **kwargs
        ) -> web.Response:
        """template.

        Return View using the Jinja2 Template System.
        """
        def _template(func):
            @wraps(func)
            async def _wrap(*args: Any) -> web.StreamResponse:
                if asyncio.iscoroutinefunction(func):
                    coro = func
                else:
                    coro = asyncio.coroutine(func)
                ## getting data:
                try:
                    context = await coro(*args)
                except Exception as err:
                    raise web.HTTPInternalServerError(
                        reason=f'Error Calling Template Function {func!r}: {err}'
                    ) from err
                if isinstance(context, web.StreamResponse):
                    ## decorator in bad position, returning context
                    return context

                # Supports class based views see web.View
                if isinstance(args[0], AbstractView):
                    request = args[0].request
                else:
                    request = args[-1]
                try:
                    tmpl = request.app['template'] # template system
                except KeyError as e:
                    raise ConfigError(
                        "NAV Template Parser need to be enabled to work with templates."
                    ) from e
                if kwargs:
                    context = {**context, **kwargs}
                result = await tmpl.render(template, params=context)
                args = {
                    "content_type": content_type,
                    "status": status,
                    "body": result
                }
                if content_type == 'application/json':
                    args["dumps"] = json_encoder
                    return web.json_response(**args)
                else:
                    args["charset"] = encoding
                    return web.Response(**args)

            return _wrap
        return _template

    def validate(self, model: Union[dataclass,BaseModel], **kwargs) -> web.Response:
        """validate.
        Description: Validate Request input using a Datamodel
        Args:
            model (Union[dataclass,BaseModel]): Model can be a dataclass or BaseModel.
            kwargs: Any other data passed as arguments to function.

        Returns:
            web.Response: add to Handler a variable with data validated.
        """
        def _validation(func, **kwargs):
            print(func, **kwargs)
            @wraps(func)
            async def _wrap(*args: Any) -> web.StreamResponse:
                ## building arguments:
                # Supports class based views see web.View
                if isinstance(args[0], AbstractView):
                    request = args[0].request
                else:
                    request = args[-1]
                sig = inspect.signature(func)
                new_args = {}
                for a, val in sig.parameters.items():
                    if isinstance(val, web.Request):
                        new_args[a] = val
                    else:
                        _t = sig.parameters[a].annotation
                        if _t == model:
                            # working on build data validation
                            data, errors = await self._validate_model(request, model)
                            new_args[a] = data
                            new_args['errors'] = errors
                        else:
                            new_args[a] = val
                if asyncio.iscoroutinefunction(func):
                    coro = func
                else:
                    coro = asyncio.coroutine(func)
                try:
                    context = await coro(**new_args)
                    return context
                except HTTPError as ex:
                    return ex
                except Exception as err:
                    raise web.HTTPInternalServerError(
                        reason=f'Error Calling Validate Function {func!r}: {err}'
                    ) from err
            return _wrap
        return _validation

    async def _validate_model(self, request: web.Request, model: Union[dataclass, BaseModel]) -> dict:
        if request.method in ('POST', 'PUT', 'PATCH'):
            # getting data from POST
            data = await request.json()
        elif request.method == 'GET':
            data = {key: val for (key, val) in request.query.items()}
        else:
            raise web.HTTPNotImplemented(
                reason=f"{request.method} Method not Implemented for Data Validation.",
                content_type="application/json"
            )
        if data is None:
            raise web.HTTPNotFound(
                reason="There is no content for validation.",
                content_type="application/json"
            )
        validated = None
        errors = None
        if isinstance(data, dict):
            try:
                validated = model(**data)
            except ValidationError as ex:
                errors = ex.payload
            except (TypeError, ValueError, AttributeError) as ex:
                errors = ex
            return validated, errors
        elif isinstance(data, list):
            validated = []
            errors = []
            for el in data:
                try:
                    valid = model(**el)
                    validated.append(valid)
                except ValidationError as ex:
                    errors.append(ex.payload)
                except (TypeError, ValueError, AttributeError) as ex:
                    errors.append(ex)
            return validated, errors
        else:
            raise web.HTTPBadRequest(
                reason="Invalid type for Data Input, expecting a Dict or List.",
                content_type="application/json"
            )


    def add_sock_endpoint(
        self, handler: Callable, name: str, route: str = "/sockjs/"
    ) -> None:
        app = self.get_app()
        sockjs.add_endpoint(app, handler, name=name, prefix=route)

    def run(self):
        """run.
        Starting App.
        """
        ### getting configuration (on runtime)
        from navigator import conf # pylint: disable=C0415
        # getting the resource App
        app = self.setup_app()
        if self.debug:
            cPrint(' :: Running in DEBUG mode :: ', level='DEBUG')
            logging.debug(' :: Running in DEBUG mode :: ')
        if self.use_ssl:
            ca_file = conf.CA_FILE
            if ca_file:
                ssl_context = ssl.create_default_context(
                    ssl.Purpose.SERVER_AUTH, cafile=ca_file
                )
            else:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            ### getting Certificates:
            ssl_cert = conf.SSL_CERT
            ssl_key = conf.SSL_KEY
            ssl_context.load_cert_chain(ssl_cert, ssl_key)
            try:
                web.run_app(
                    app, host=self.host, port=self.port, ssl_context=ssl_context
                )
            except Exception as err:
                logging.exception(err, stack_info=True)
                raise
        elif self.path:
            web.run_app(app, path=self.path, loop=self._loop)
        else:
            web.run_app(app, host=self.host, port=self.port, loop=self._loop)
