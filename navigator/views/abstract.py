from typing import Optional, Union, Any, TypeVar
from collections.abc import Callable
import asyncio
from aiohttp import web, hdrs
import traceback
from functools import wraps
from asyncdb import AsyncDB, AsyncPool
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from datamodel.types import JSON_TYPES
from navigator_session import get_session
from ..conf import (
    default_dsn,
    AUTH_SESSION_OBJECT
)
from ..types import WebApp
from ..applications.base import BaseApplication
from ..exceptions import ConfigError
from .base import BaseView


F = TypeVar("F", bound=Callable[..., Any])

class NotSet(BaseException):
    """Usable for not set Value on Field"""


class ConnectionHandler:
    def __init__(
        self,
        driver: str = 'pg',
        dsn: str = None,
        dbname: str = 'nav.model',
        credentials: dict = None
    ):
        self.dsn = dsn
        self.credentials = credentials
        self.driver = driver
        self._default: bool = False
        self._db = None
        self._dbname = dbname

    def connection(self):
        return self._db

    async def __call__(self, request: web.Request):
        self._db = await self.get_connection(request)
        return self

    async def __aenter__(self):
        if self._default is True:
            self._connection = await self._db.acquire()
            return self._connection
        else:
            return await self._db.connection()

    async def default_connection(self, request: web.Request):
        if self._dbname in request.app:
            return request.app[self._dbname]
        kwargs = {
            "server_settings": {
                'client_min_messages': 'notice',
                'max_parallel_workers': '24',
                'tcp_keepalives_idle': '30'
            }
        }
        pool = AsyncPool(
            self.driver,
            dsn=default_dsn,
            loop=asyncio.get_event_loop(),
            **kwargs
        )
        await pool.connect()
        request.app[self._dbname] = pool
        return pool

    async def get_connection(self, request: web.Request):
        if self.dsn:
            # using DSN as connection string
            db = AsyncDB(
                self.driver,
                dsn=self.dsn,
                loop=asyncio.get_event_loop()
            )
        elif self.credentials:
            db = AsyncDB(
                self.driver,
                params=self.credentials,
                loop=asyncio.get_event_loop()
            )
        else:
            # Using Default Connection
            self._default = True
            try:
                db = request.app["database"]
            except KeyError:
                db = await self.default_connection(request)
        return db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Assuming the connection has a close or release method
        # Adjust based on your specific database library
        if self._default:
            await self._db.release(
                self._connection
            )
        else:
            await self._db.close()


class AbstractModel(BaseView):
    """AbstractModel.

    description: Usable for any dataclass or DataModel.
    tags:
      - Model
      - dataclass
      - python-datamodel
    parameters:
      - name: model
        in: Model
        type: BaseModel
        required: true
    """
    model: BaseModel = None
    # Signal for startup method for this ModelView
    on_startup: Optional[Callable] = None
    on_shutdown: Optional[Callable] = None
    name: str = "Model"

    def __init__(self, request, *args, **kwargs):
        self.__name__ = self.model.__name__
        self._session = None
        driver = kwargs.pop('driver', 'pg')
        dsn = kwargs.pop('dsn', None)
        credentials = kwargs.pop('credentials', {})
        dbname = kwargs.pop('dbname', 'nav.model')
        super().__init__(request, *args, **kwargs)
        # Database Connection Handler
        self.handler = ConnectionHandler(
            driver,
            dsn=dsn,
            dbname=dbname,
            credentials=credentials
        )

    @classmethod
    def configure(cls, app: WebApp, path: str = None) -> WebApp:
        """configure.


        Args:
            app (WebApp): aiohttp Web Application instance.
            path (str, optional): route path for Model.

        Raises:
            TypeError: Invalid aiohttp Application.
            ConfigError: Wrong configuration parameters.
        """
        if isinstance(app, BaseApplication):  # migrate to BaseApplication (on types)
            app = app.get_app()
        elif isinstance(app, WebApp):
            app = app  # register the app into the Extension
        else:
            raise TypeError(
                f"Invalid type for Application Setup: {app}:{type(app)}"
            )
        # startup operations over extension backend
        if callable(cls.on_startup):
            app.on_startup.append(cls.on_startup)
        if callable(cls.on_shutdown):
            app.on_shutdown.append(cls.on_shutdown)
        ### added routers:
        try:
            model_path = cls.path
        except AttributeError:
            model_path = None
        if not model_path:
            model_path = path
        if not model_path:
            raise ConfigError(
                "Wrong Model Configuration: URI path must be provided."
            )
        url = f"{model_path}"
        app.router.add_view(
            r"{url}/{{id:.*}}".format(url=url), cls
        )
        app.router.add_view(
            r"{url}{{meta:(:.*)?}}".format(url=url), cls
        )

    async def validate_payload(self):
        """Get information for usage in Form."""
        data = await self.json_data()
        if not data:
            headers = {"x-error": f"{self.__name__} POST data Missing"}
            self.error(
                response={
                    "message": f"{self.__name__} POST data Missing"
                },
                headers=headers,
                status=412
            )
        # Validate Data, if valid, return a DataModel.
        try:
            return self.model(**data)
        except TypeError as ex:
            error = {
                "error": f"Error on {self.__name__}: {ex}",
                "payload": f"{data!r}",
            }
            return self.error(
                response=error, status=400
            )
        except ValidationError as ex:
            error = {
                "error": f"Bad Data for {self.__name__}: {ex}",
                "payload": f"{ex.payload!r}",
            }
            return self.error(
                response=error, status=400
            )

    async def get_userid(self, session, idx: str = 'user_id') -> int:
        if not session:
            self.error(
                response={"error": "Unauthorized"},
                status=403
            )
        try:
            if AUTH_SESSION_OBJECT in session:
                return session[AUTH_SESSION_OBJECT][idx]
            else:
                return session[idx]
        except KeyError:
            self.error(
                response={
                    "error": "Unauthorized",
                    "message": "Hint: maybe you need to pass an Authorization token."
                },
                status=403
            )

    @staticmethod
    def service_groups(groups: list, *args, **kwargs):
        def _wrapper(fn: F) -> Any:
            @wraps(fn)
            async def _wrap(self, *args, **kwargs) -> web.StreamResponse:
                request = self.request
                if request.get("authenticated", False) is False:
                    # check credentials:
                    raise web.HTTPUnauthorized(
                        reason="Access Denied",
                        headers={
                            hdrs.CONTENT_TYPE: "application/json",
                            hdrs.CONNECTION: "keep-alive",
                        },
                    )
                # User is authenticated
                self._userid = await self.get_userid(self._session)
                self.logger.info(
                    f"Scheduler: Authenticated User: {self._userid}"
                )
                # get user information:
                userinfo = self._session.get(AUTH_SESSION_OBJECT, {})
                if userinfo.get("superuser", False) is True:
                    self.logger.info(
                        f"Audit: User {self._userid} is calling {fn!r}"
                    )
                    return await fn(self, *args, **kwargs)
                if "groups" in userinfo:
                    member = bool(
                        not set(userinfo["groups"]).isdisjoint(groups)
                    )
                    if member:
                        self.logger.info(
                            f"Audit: User {self._userid} is calling {fn!r}"
                        )
                        return await fn(self, *args, **kwargs)
                raise web.HTTPForbidden(
                    reason="Access Denied",
                    headers={
                        hdrs.CONTENT_TYPE: "application/json",
                        hdrs.CONNECTION: "keep-alive",
                    },
                )
            return _wrap
        return _wrapper

    @staticmethod
    def service_auth(fn: Union[Any, Any]) -> Any:
        async def _wrap(self, *args, **kwargs):
            ## get User Session:
            await self.session()
            if self._session:
                self._userid = await self.get_userid(self._session)
            # TODO: Checking User Permissions:
            ## Calling post-authorization Model:
            await self._post_auth(self, *args, **kwargs)
            return await fn(self, *args, **kwargs)
        return _wrap

    async def _post_auth(self, *args, **kwargs):
        """Post-authorization Model."""
        return True

    async def session(self):
        # TODO: Add ABAC Support.
        self._session = None
        try:
            self._session = await get_session(self.request)
        except (ValueError, RuntimeError) as err:
            return self.critical(
                response={"error": "Error Decoding Session"},
                exception=err
            )
        if not self._session:
            # TODO: add support for service tokens
            if hasattr(self.model.Meta, 'allowed_methods'):
                if self.request.method in self.model.Meta.allowed_methods:
                    self.logger.warning(
                        f"{self.model.__name__}.{self.request.method} Accepted by Exclusion"
                    )
                    ## Query can be made anonymously.
                    return True
            self.error(
                response={
                    "error": "Unauthorized",
                    "message": "Hint: maybe need to login and pass Authorization token."
                },
                status=403
            )

    def get_args(self, request: web.Request = None) -> dict:
        params = {}
        for arg, val in self.request.match_info.items():
            try:
                object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        return params

    def get_parameters(self):
        """Get Parameters.

        Get all parameters from URL or from query string.
        """
        args = self.get_args()
        meta = args.pop('meta', None)
        qp = self.query_parameters(self.request)
        try:
            fields = qp['fields'].split(',')
            del qp['fields']
        except KeyError:
            fields = None
        return [args, meta, qp, fields]

    @service_auth
    async def head(self):
        """Getting Model information."""
        ## calculating resource:
        response = self.model.schema(as_dict=True)
        columns = list(response["properties"].keys())
        size = len(str(response))
        schema = self.model.Meta.schema if self.model.Meta.schema else 'public'
        headers = {
            "Content-Length": size,
            "X-Columns": f"{columns!r}",
            "X-Model": self.model.__name__,
            "X-Tablename": self.model.Meta.name,
            "X-Schema": schema,
            "X-Table": f"{schema}.{self.model.Meta.name}"
        }
        return self.no_content(headers=headers)

    async def _get_meta_info(self, meta: str, fields: list):
        """GET Model information."""
        if meta == ":meta":
            # returning JSON schema of Model:
            response = self.model.schema(as_dict=True)
            return self.json_response(response)
        elif meta == ':sample':
            # return a JSON sample of data:
            response = self.model.sample()
            return self.json_response(response)
        elif meta == ':info':
            ## return Column Info:
            try:
                # getting metadata of Model
                data = {}
                for _, field in self.model.get_columns().items():
                    key = field.name
                    _type = field.db_type()
                    _t = JSON_TYPES[field.type]
                    default = None
                    if field.default is not None:
                        default = f"{field.default!r}"
                    data[key] = {
                        "type": _t,
                        "db_type": _type,
                        "default": default
                    }
                return await self._model_response(data, fields=fields)
            except Exception as err:  # pylint: disable=W0703
                print(err)
                stack = traceback.format_exc()
                return self.critical(
                    exception=err, stacktrace=stack
                )
        else:
            return None

    # Pre and post operations:
    async def _pre_get(self, *args, **kwargs):
        """Pre-get Model."""
        return True

    async def _pre_patch(self, *args, **kwargs):
        """Post-get Model."""
        return True

    async def _pre_put(self, *args, **kwargs):
        """Pre-put Model."""
        return True

    async def _pre_post(self, *args, **kwargs):
        """Post-put Model."""
        return True

    async def _pre_delete(self, *args, **kwargs):
        """Pre-delete Model."""
        return True
