import contextlib
from pathlib import Path
from typing import Any, Union, Optional
from collections.abc import Callable
import ssl
import asyncio
import signal
import inspect
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from dataclasses import dataclass
from datamodel.parsers.json import json_encoder
from datamodel.exceptions import ValidationError
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web_exceptions import HTTPError
try:
    import sockjs
except ImportError:
    sockjs = None
try:
    from navconfig import config
    from navconfig.logging import logging
except FileExistsError:
    # NavConfig is not Installed:
    import logging
    logging.exception(
        "NavConfig is not installed, please install it. "
        "pip install navconfig[default]."
    )

try:
    from navigator_auth.conf import exclude_list
    AUTH_INSTALLED = True
except ImportError:
    AUTH_INSTALLED = False

from .exceptions.handlers import nav_exception_handler, shutdown
from .handlers import BaseAppHandler
from .functions import cPrint
from .exceptions import NavException, ConfigError, InvalidArgument

# Template Extension.
from .template import TemplateParser

# websocket resources
from .services.ws import WebSocketHandler
from .types import WebApp


from .applications.base import BaseApplication
from .applications.startup import ApplicationInstaller


FORCED_CIPHERS = (
    "ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+AES:ECDH+HIGH:"
    "DH+HIGH:ECDH+3DES:DH+3DES:RSA+AESGCM:RSA+AES:RSA+HIGH:RSA+3DES"
)


class Application(BaseApplication):
    """Application.

        Main class for Navigator Application.
    Args:
        Handler (BaseAppHandler): Main (principal) Application to be wrapped by Navigator.
    """

    def __init__(
        self,  # pylint: disable=W0613
        handler: BaseAppHandler = None,
        title: str = "",
        description: str = "NAVIGATOR APP",
        contact: str = "",
        enable_jinja2: bool = False,
        template_dirs: list = None,
        **kwargs,
    ) -> None:
        super(Application, self).__init__(
            handler=handler,
            title=title,
            contact=contact,
            description=description,
            **kwargs,
        )
        self._middlewares: list = kwargs.pop('middlewares', [])
        self.enable_jinja2 = enable_jinja2
        self.template_dirs = template_dirs
        from navigator.conf import Context  # pylint: disable=C0415
        self._runner: Optional[web.AppRunner] = None
        self._sites: list = []
        self._shutdown_timeout = 30.0
        # configuring asyncio loop
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
        if 'evt' in kwargs:
            self._loop = kwargs.pop('evt')
        self._loop.set_exception_handler(nav_exception_handler)
        asyncio.set_event_loop(self._loop)
        # May want to catch other signals too
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            self._loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(self._loop, s))
            )
        # here:
        if not handler:
            default_handler = config.get("default_handler", fallback="AppHandler")
            try:
                cls = import_module("navigator.handlers.types", package=default_handler)
                app_obj = getattr(cls, default_handler)
                # create an instance of AppHandler
                self.handler: BaseAppHandler = app_obj(Context, evt=self._loop)
            except ImportError as ex:
                raise NavException(
                    f"Cannot Import default App Handler {default_handler}: {ex}"
                ) from ex
        else:
            self.handler: BaseAppHandler = handler(Context, evt=self._loop)

    def setup_app(self) -> WebApp:
        app = self.handler.app
        if self.enable_jinja2 is True:
            try:
                # TODO: passing more parameters via configuration.
                parser = TemplateParser(template_dir=self.template_dirs)
                parser.setup(app)
            except Exception as e:
                logging.exception(e)
                raise ConfigError(
                    f"Error on Template configuration, {e}"
                ) from e
        if self._middlewares:
            for middleware in self._middlewares:
                app.middlewares.append(middleware)
        # setup The Application and Sub-Applications Startup
        installer = ApplicationInstaller()
        INSTALLED_APPS: list = installer.installed_apps()
        # load dynamically the app Startup:
        try:
            app_init = config.get(
                "APP_STARTUP", fallback="navigator.applications.startup"
            )
            cls = import_module(app_init, package="app_startup")
            app_startup = getattr(cls, "app_startup")
            app_startup(
                INSTALLED_APPS,
                app,
                context=app["config"]
            )
        except ImportError as ex:
            raise NavException(
                f"Exception: Can't load Application Startup: {app_init}"
            ) from ex
        # Configure Routes and other things:
        self.handler.configure()
        self.handler.setup_docs()
        self.handler.setup_cors()
        ## Return aiohttp Application.
        return app

    def add_websockets(self, base_path: str = 'ws') -> None:
        """
        add_websockets.
        description: enable support for websockets in the main App
        """
        app = self.get_app()
        if self.debug:
            self.logger.debug(
                ":: Enabling WebSockets ::"
            )
        # websockets
        path = f"/{base_path}/"
        app.router.add_view(f"{path}{{channel}}", WebSocketHandler)

    def add_routes(self, routes: list) -> None:
        """
        add_routes
        description: append a list of routes to routes dict
        """
        # TODO: avoid to add same route different times
        try:
            self.handler.add_routes(routes)
        except Exception as ex:
            raise NavException(f"Error adding routes: {ex}") from ex

    def add_route(
        self, method: str = "GET", route: str = None, fn: Callable = None
    ) -> None:
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
                self.logger.exception(err)
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
            self.get_app().router.add_route(
                method, route, self.threaded_func(func, threaded)
            )
            return func

        return _decorator

    def add_get(self, route: str, threaded: bool = False) -> Callable:
        def _decorator(func):
            self.get_app().router.add_get(
                route, self.threaded_func(func, threaded), allow_head=False
            )
            return func

        return _decorator

    def Response(self, content: Any) -> web.Response:
        return web.Response(text=content)

    @property
    def router(self):
        return self.get_app().router

    def auth_excluded(self, route: str):
        if AUTH_INSTALLED:
            exclude_list.append(route)

    def get(self, route: str, allow_anonymous: bool = False):
        app = self.get_app()

        def _decorator(func):
            if allow_anonymous:
                # add this route to the exclude list:
                self.auth_excluded(route)
            r = app.router.add_get(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self.logger.exception(err)
                    raise ConfigError(
                        f"Error configuring GET Route {route}: {err}"
                    ) from err

            return _wrap

        return _decorator

    def post(self, route: str, allow_anonymous: bool = False):
        def _decorator(func):
            if allow_anonymous:
                # add this route to the exclude list:
                self.auth_excluded(route)
            self.get_app().router.add_post(route, func)

            @wraps(func)
            async def _wrap(request, *args, **kwargs):
                try:
                    return f"{func(request, args, **kwargs)}"
                except Exception as err:
                    self.logger.exception(err)
                    raise ConfigError(
                        f"Error configuring POST Route {route}: {err}"
                    ) from err

            return _wrap

        return _decorator

    def template(
        self,
        template: str,
        content_type: str = "text/html",
        encoding: str = "utf-8",
        status: int = 200,
        **kwargs,
    ) -> web.Response:
        """template.

        Return View using the Jinja2 Template System.
        """

        def _template(func):
            @wraps(func)
            async def _wrap(*args: Any) -> web.StreamResponse:
                coro = func if asyncio.iscoroutinefunction(func) else asyncio.coroutine(func)
                ## getting data:
                try:
                    context = await coro(*args)
                except Exception as err:
                    raise web.HTTPInternalServerError(
                        reason=f"Error Calling Template Function {func!r}: {err}"
                    ) from err
                if isinstance(context, web.StreamResponse):
                    ## decorator in bad position, returning context
                    return context

                # Supports class based views see web.View
                request = args[0].request if isinstance(args[0], AbstractView) else args[-1]
                try:
                    tmpl = request.app["template"]  # template system
                except KeyError as e:
                    raise ConfigError(
                        "NAV Template Parser need to be enabled to work with templates."
                    ) from e
                if kwargs:
                    context = {**context, **kwargs}
                result = await tmpl.render(template, params=context)
                args = {"content_type": content_type, "status": status, "body": result}
                if content_type == "application/json":
                    args["dumps"] = json_encoder
                    return web.json_response(**args)
                else:
                    args["charset"] = encoding
                    return web.Response(**args)

            return _wrap

        return _template

    def validate(self, model: Union[dataclass, Any], **kwargs) -> web.Response:
        """validate.
        Description: Validate Request input using a dataclass or Datamodel.
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
                request = args[0].request if isinstance(args[0], AbstractView) else args[-1]
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
                            new_args["errors"] = errors
                        else:
                            new_args[a] = val
                coro = func if asyncio.iscoroutinefunction(func) else asyncio.coroutine(func)
                try:
                    context = await coro(**new_args)
                    return context
                except HTTPError as ex:
                    return ex
                except Exception as err:
                    raise web.HTTPInternalServerError(
                        reason=f"Error Calling Validate Function {func!r}: {err}"
                    ) from err

            return _wrap

        return _validation

    async def _validate_model(
        self, request: web.Request, model: Union[dataclass, Any]
    ) -> dict:
        if request.method in ("POST", "PUT", "PATCH"):
            # getting data from POST
            data = await request.json()
        elif request.method == "GET":
            data = dict(request.query.items())
        else:
            raise web.HTTPNotImplemented(
                reason=f"{request.method} Method not Implemented for Data Validation.",
                content_type="application/json",
            )
        if data is None:
            raise web.HTTPNotFound(
                reason="There is no content for validation.",
                content_type="application/json",
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
                content_type="application/json",
            )

    def add_sock_endpoint(
        self, handler: Callable, name: str, route: str = "/sockjs/"
    ) -> None:
        app = self.get_app()
        sockjs.add_endpoint(app, handler, name=name, prefix=route)

    def _generate_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Generate SSL context from configuration.

        Returns:
            ssl.SSLContext: Configured SSL context or None if SSL disabled.
        """
        if not self.use_ssl:
            return None

        try:
            from navigator import conf  # pylint: disable=C0415

            self.logger.debug("Configuring SSL context")

            ca_file = getattr(conf, 'CA_FILE', None)
            if ca_file:
                ssl_context = ssl.create_default_context(
                    ssl.Purpose.CLIENT_AUTH,
                    cafile=ca_file
                )
            else:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

            # Load certificates
            ssl_cert = getattr(conf, 'SSL_CERT', None)
            ssl_key = getattr(conf, 'SSL_KEY', None)

            if not ssl_cert or not ssl_key:
                raise ValueError("SSL_CERT and SSL_KEY must be configured for SSL mode")

            ssl_context.load_cert_chain(ssl_cert, ssl_key)
            ssl_context.set_ciphers(FORCED_CIPHERS)

            self.logger.info(f"SSL enabled with cert: {ssl_cert}")
            return ssl_context

        except Exception as err:
            self.logger.exception("Failed to configure SSL context: %s", err)
            raise

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        if not hasattr(signal, 'SIGTERM'):
            # Windows doesn't have all signals
            return

        def signal_handler(signame):
            """Handle received OS signals and initiate graceful shutdown.

            This function logs the received signal and schedules the application's graceful shutdown.

            Args:
                signame: Name of the received signal.
            """
            if hasattr(self, '_shutdown_in_progress') and self._shutdown_in_progress:  # pylint: disable=E0203 # noqa
                self.logger.warning(
                    f"Received {signame} but shutdown already in progress"
                )
                return
            self.logger.info(f"Received {signame}, initiating graceful shutdown...")
            self._shutdown_in_progress = True
            # Trigger the shutdown event if it exists
            if hasattr(self, '_shutdown_event') and self._shutdown_event:
                self._shutdown_event.set()

        try:
            loop = asyncio.get_running_loop()
            for sig in [signal.SIGTERM, signal.SIGINT]:
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: signal_handler(s.name)
                )
        except RuntimeError:
            # Signal handling not available on this platform or no running loop
            self.logger.warning("Signal handling not available")

    async def _graceful_shutdown(self) -> None:
        """Perform graceful shutdown of the application."""
        self.logger.info("Starting graceful shutdown...")

        try:
            # Cleanup the runner
            if self._runner:
                await self._runner.cleanup()
            self._sites.clear()
            self._runner = None

        except Exception as err:
            self.logger.exception(
                "Error during graceful shutdown: %s", err
            )
        finally:
            self._runner = None
            self.logger.info(
                "Navigator Shutdown completed"
            )

    async def _run_tcp(
        self,
        app: web.Application,
        host: str = None,
        port: int = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        handle_signals: bool = False,
        **kwargs
    ) -> None:
        """Run application with TCP transport.

        Args:
            app: aiohttp Application instance
            host: Host to bind to
            port: Port to bind to
            ssl_context: SSL context for HTTPS
            **kwargs: Additional arguments for TCPSite
        """
        host = host or self.host
        port = port or self.port

        try:
            runner_kwargs = {
                'handle_signals': handle_signals,
                'keepalive_timeout': kwargs.get('keepalive_timeout', 30),
                'client_timeout': kwargs.get('client_timeout', 60),
                'max_request_size': kwargs.get('max_request_size', 1024**2),
            }
            # Only add these if they're explicitly provided (not None)
            if 'access_log_class' in kwargs and kwargs['access_log_class'] is not None:
                runner_kwargs['access_log_class'] = kwargs['access_log_class']

            if 'access_log' in kwargs:
                runner_kwargs['access_log'] = kwargs['access_log']

            if 'access_log_format' in kwargs and kwargs['access_log_format'] is not None:
                runner_kwargs['access_log_format'] = kwargs['access_log_format']

            # Create and setup runner
            self._runner = web.AppRunner(app, **runner_kwargs)
            await self._runner.setup()

            # Create TCP site
            site = web.TCPSite(
                self._runner,
                host=host,
                port=port,
                ssl_context=ssl_context,
                backlog=kwargs.get('backlog', 128),
                reuse_address=kwargs.get('reuse_address', True),
                reuse_port=kwargs.get('reuse_port', False),
            )

            await site.start()
            self._sites.append(site)

            protocol = "https" if ssl_context else "http"
            self.logger.notice(
                f":: Navigator started on {protocol}://{host}:{port}"
            )

            if self.debug:
                self.logger.debug("Running in DEBUG mode")

        except OSError as err:
            if err.errno == 98:  # Address already in use
                self.logger.error(f"Port {port} is already in use")
            else:
                self.logger.error(f"Failed to bind to {host}:{port} - {err}")
            raise
        except Exception as err:
            self.logger.exception("Failed to start TCP server: %s", err)
            raise

    async def _run_unix(
        self,
        app: web.Application,
        path: Union[str, Path],
        **kwargs
    ) -> None:
        """Run application with Unix domain socket transport.

        Args:
            app: aiohttp Application instance
            path: Unix socket path
            **kwargs: Additional arguments for UnixSite
        """
        try:
            # Ensure path is a Path object
            if isinstance(path, str):
                path = Path(path)

            # Remove existing socket file if it exists
            if path.exists():
                path.unlink()
                self.logger.debug(f"Removed existing socket: {path}")

            # Create and setup runner
            self._runner = web.AppRunner(
                app,
                handle_signals=False,
                access_log=kwargs.get('access_log'),
                keepalive_timeout=kwargs.get('keepalive_timeout', 30),
            )
            await self._runner.setup()

            # Create Unix site
            site = web.UnixSite(
                self._runner,
                path=str(path),
                **kwargs
            )

            await site.start()
            self._sites.append(site)

            self.logger.info(f"Navigator started on unix socket: {path}")

        except Exception as err:
            self.logger.exception("Failed to start Unix socket server: %s", err)
            raise

    async def _run_http(self, **kwargs) -> None:
        """Run HTTP server (legacy compatibility method)."""
        from navigator import conf  # pylint: disable=C0415

        # Get configuration
        enable_access_log = getattr(conf, 'ENABLE_ACCESS_LOG', True)
        if enable_access_log is False:
            enable_access_log = None

        # Generate SSL context
        ssl_context = self._generate_ssl_context()

        # Get the application
        app = self.setup_app()

        # Configure access logging
        kwargs.setdefault('access_log', enable_access_log)

        # Choose transport method
        if self.path:
            await self._run_unix(app, self.path, **kwargs)
        else:
            await self._run_tcp(app, ssl_context=ssl_context, **kwargs)

    async def start_server(
        self,
        host: str = None,
        port: int = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        unix_path: Union[str, Path] = None,
        **kwargs
    ) -> None:
        """Start the Navigator server with modern AppRunner pattern.

        Args:
            host: Host to bind to (overrides instance default)
            port: Port to bind to (overrides instance default)
            ssl_context: SSL context for HTTPS
            unix_path: Unix socket path (if provided, TCP is ignored)
            **kwargs: Additional server configuration
        """
        try:
            # Setup signal handlers
            self._setup_signal_handlers()

            # Get the application
            app = self.setup_app()

            if unix_path:
                await self._run_unix(app, unix_path, **kwargs)
            else:
                await self._run_tcp(
                    app,
                    host=host,
                    port=port,
                    ssl_context=ssl_context,
                    **kwargs
                )

            # Keep running until shutdown
            try:
                shutdown_event = asyncio.Event()
                self._shutdown_event = shutdown_event
                await shutdown_event.wait()
            except asyncio.CancelledError:
                self.logger.info("Server shutdown requested")

        except Exception as err:
            self.logger.exception("Server startup failed: %s", err)
            raise
        finally:
            await self._graceful_shutdown()

    def run(
        self,
        host: str = None,
        port: int = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        unix_path: Union[str, Path] = None,
        **kwargs
    ) -> None:
        """Run the Navigator application.

        This method provides both legacy compatibility and modern features.

        Args:
            host: Host to bind to
            port: Port to bind to
            ssl_context: SSL context (if None, will be generated from config if use_ssl=True)
            unix_path: Unix socket path
            **kwargs: Additional server configuration
        """
        try:
            # If no event loop is running, create one and run the server
            with contextlib.suppress(RuntimeError):
                loop = asyncio.get_running_loop()
                self.logger.warning("Event loop already running, creating task")
                # If we're already in an event loop, just create a task
                return asyncio.create_task(
                    self.start_server(host, port, ssl_context, unix_path, **kwargs)
                )

            # Use the configured event loop if available
            if self._loop:
                asyncio.set_event_loop(self._loop)
                loop = self._loop
            else:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

            # For compatibility with existing code that might expect web.run_app behavior
            if kwargs.get('use_legacy_runner', False):
                self._run_legacy(**kwargs)
                return

            # Modern async server startup
            try:
                loop.run_until_complete(
                    self.start_server(host, port, ssl_context, unix_path, **kwargs)
                )
            except KeyboardInterrupt:
                self.logger.info(
                    "Received KeyboardInterrupt, shutting down..."
                )
            finally:
                # Ensure cleanup happens
                if not getattr(self, '_shutdown_in_progress', False):
                    loop.run_until_complete(self._graceful_shutdown())

                if not loop.is_closed():
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                    loop.close()

        except Exception as err:
            self.logger.exception("Application startup failed: %s", err)
            raise

    def _run_legacy(self, **kwargs) -> None:
        """Legacy run method using web.run_app (for backward compatibility).

        This method maintains compatibility with the old Navigator behavior.
        """
        self.logger.warning(
            "Using legacy runner (web.run_app). Consider upgrading to modern AppRunner pattern."
        )

        try:
            from navigator import conf  # pylint: disable=C0415

            # Get configuration
            enable_access_log = getattr(conf, 'ENABLE_ACCESS_LOG', True)
            if enable_access_log is False:
                enable_access_log = None

            # Get the application
            app = self.setup_app()

            if self.debug:
                self.logger.debug("Running in DEBUG mode")

            # SSL configuration
            if self.use_ssl:
                self.logger.debug("Running in SSL mode")
                ssl_context = self._generate_ssl_context()

                web.run_app(
                    app,
                    host=self.host,
                    port=self.port,
                    ssl_context=ssl_context,
                    handle_signals=True,
                    access_log=enable_access_log,
                    **kwargs
                )
            elif self.path:
                # Unix socket
                web.run_app(
                    app,
                    path=self.path,
                    loop=self._loop,
                    handle_signals=True,
                    access_log=enable_access_log,
                    **kwargs
                )
            else:
                # Regular HTTP
                web.run_app(
                    app,
                    host=self.host,
                    port=self.port,
                    loop=self._loop,
                    handle_signals=True,
                    access_log=enable_access_log,
                    **kwargs
                )

        except Exception as err:
            self.logger.exception(
                "Legacy runner failed with: %s", err
            )
            raise


# Utilities functions for direct AppRunner usage
async def create_app_runner(
    app: web.Application,
    **runner_kwargs
) -> web.AppRunner:
    """Create and setup an AppRunner instance.

    Args:
        app: aiohttp Application
        **runner_kwargs: Arguments for AppRunner

    Returns:
        web.AppRunner: Configured and setup AppRunner
    """
    runner = web.AppRunner(app, **runner_kwargs)
    await runner.setup()
    return runner


async def create_tcp_site(
    runner: web.AppRunner,
    host: str = 'localhost',
    port: int = 8080,
    ssl_context: Optional[ssl.SSLContext] = None,
    **site_kwargs
) -> web.TCPSite:
    """Create and start a TCPSite.

    Args:
        runner: AppRunner instance
        host: Host to bind to
        port: Port to bind to
        ssl_context: SSL context for HTTPS
        **site_kwargs: Arguments for TCPSite

    Returns:
        web.TCPSite: Started TCPSite
    """
    site = web.TCPSite(
        runner,
        host=host,
        port=port,
        ssl_context=ssl_context,
        **site_kwargs
    )
    await site.start()
    return site


async def create_unix_site(
    runner: web.AppRunner,
    path: Union[str, Path],
    **site_kwargs
) -> web.UnixSite:
    """Create and start a UnixSite.

    Args:
        runner: AppRunner instance
        path: Unix socket path
        **site_kwargs: Arguments for UnixSite

    Returns:
        web.UnixSite: Started UnixSite
    """
    site = web.UnixSite(runner, path=str(path), **site_kwargs)
    await site.start()
    return site
