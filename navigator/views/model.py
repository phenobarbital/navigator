from typing import Union, Any, Optional
import asyncio
import traceback
from aiohttp import web
from navconfig.logging import logger
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from asyncdb.models import Model
from asyncdb.exceptions import (
    ProviderError,
    DriverError,
    NoDataFound,
    ModelError,
    StatementError
)
from navigator_session import get_session
from navigator.conf import AUTH_SESSION_OBJECT
from navigator.exceptions import (
    NavException,
    ConfigError
)
from .base import BaseView


async def load_models(app: str, model, tablelist: list):
    pool = app["database"]
    async with await pool.acquire() as conn:
        name = app["name"]
        if isinstance(tablelist, list):
            for table in tablelist:
                try:
                    obj = await load_model(
                        tablename=table,
                        schema=name,
                        connection=conn
                    )
                    model[table] = obj
                except Exception as err:  # pylint: disable=W0703
                    logger.error(f"Error loading Model {table}: {err!s}")
            return model


async def load_model(tablename: str, schema: str, connection: Any) -> Model:
    try:
        mdl = await Model.makeModel(name=tablename, schema=schema, db=connection)
        logger.notice(f'Model: {tablename} {mdl}')
        return mdl
    except Exception as err: # pylint: disable=W0703
        logger.error(
            f"Error loading Model {tablename}: {err!s}"
        )

class ModelView(BaseView):
    """ModelView.

    description: API View using AsyncDB Models.
    tags:
      - Model
      - AsyncDB Model
    parameters:
      - name: model
        in: Model
        type: Model
        required: true
        description: DB Model using asyncdb Model.
    """

    model: BaseModel = None
    get_model: BaseModel = None
    name: str = "Model"
    pk: Union[str, list] = "id"
    _required: list = []
    _primaries: list = []
    _hidden: list = []

    def __init__(self, request, *args, **kwargs):
        self.__name__ = self.__class__.__name__
        self._session = None
        super(ModelView, self).__init__(request, *args, **kwargs)
        # getting model associated
        try:
            self.model = self._get_model()
        except NoDataFound as err:
            raise ConfigError(
                f"{self.model}: {err}"
            ) from err
        ## getting get Model:
        if not self.get_model:
            self.get_model = self._get_model()

    def _get_model(self):
        if self.model:
            ## Fill Primary and Required for this Model:
            if not self._primaries:
                for name, field in self.model.get_columns().items():
                    try:
                        if field.metadata["required"] is True:
                            self._required.append(name)
                    except KeyError:
                        pass
                    try:
                        if field.metadata["primary"] is True:
                            self._primaries.append(name)
                    except KeyError:
                        pass
                    if not self._hidden:
                        try:
                            if field.metadata["repr"] is False:
                                self._hidden.append(name)
                        except KeyError:
                            pass
            return self.model
        else:
            # loop = asyncio.get_running_loop()
            # try:
            #     table = self.Meta.tablename
            # except (TypeError, AttributeError) as err:  # pylint: disable=W0703
            #     print(err)
            #     table = type(self).__name__
            # try:
            #     self.model = loop.run_until_complete(
            #         load_model(tablename=table, schema=self.schema, connection=None)
            #     )
            # Model doesn't exists
            raise NoDataFound(
                f"Model {table} Doesn't Exists"
            ) from err

    def service_auth(fn: Union[Any, Any]) -> Any:
        async def _wrap(self, *args, **kwargs):
            ## get User Session:
            await self.session()
            self._userid = await self.get_userid(self._session)
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
            if hasattr(self.model.Meta, 'allowed_methods'):
                if self.request.method in self.model.Meta.allowed_methods:
                    self.logger.warning(
                        f"{self.model.__name__}.{self.request.method} Accepted by exclusion"
                    )
                    ## Query can be made anonymously.
                    return True
            self.error(
                response={
                    "message": "Unauthorized",
                    "message": "Hint: maybe you need to login and pass an Authorization token."
                },
                status=403
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
                    "message": "Hint: maybe you need to login and pass an Authorization token."
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
        try:
            meta = args["meta"]
            del args["meta"]
        except KeyError:
            meta = None
        qp = self.query_parameters(self.request)
        try:
            fields = qp['fields'].split(',')
            del qp['fields']
        except KeyError:
            fields = None
        return [args, meta, qp, fields]

    async def _model_response(
            self,
            response: Any,
            fields: list = None,
            headers: dict = None,
            status: int = 200
    ) -> web.Response:
        if response is None:
            return self.no_content(headers=headers)
        if not response:
            return self.error(
                response={
                    "error": f"Resource {self.__name__} not Found"
                },
                headers=headers
            )
        # return data only
        if fields is not None:
            _fields = fields
        elif self._hidden is not None:
            _fields = self._hidden
        if _fields:
            if isinstance(response, list):
                new = []
                for r in response:
                    row = {}
                    for field in _fields:
                        row[field] = getattr(r, field, None)
                    new.append(row)
                result = new
            else:
                ## filtering result to returning only fields asked:
                result = {}
                for field in _fields:
                    result[field] = getattr(response, field, None)
        else:
            result = response
        return self.json_response(result, headers=headers, status=status)

    def get_primary(self, data: dict) -> Any:
        """get_primary.

            Get Primary Id from Parameters.
        """
        objid = None
        if isinstance(self.pk, str):
            if isinstance(data, list):
                pk = [self.pk]
                objid = []
                for entry in data:
                    new_entry = {field: entry[field] for field in pk}
                    objid.append(new_entry)
                return objid
            else:
                try:
                    objid = data[self.pk]
                except (TypeError, KeyError) as err:
                    try:
                        objid = data["id"]
                        if objid == '':
                            objid = None
                    except KeyError:
                        objid = None
                ## but if objid has /
                if '/' in objid:
                    return objid.split('/')
                return objid
        elif isinstance(self.pk, list):
            if 'id' in data:
                try:
                    paramlist = data["id"].split("/")
                    if len(paramlist) != len(self.pk):
                        return self.error(
                            reason=f"Invalid Number of URL elements for PK: {self.pk}, {paramlist!r}",
                            status=410,
                        )
                    args = {}
                    for key in self.pk:
                        args[key] = paramlist.pop(0)
                    return args
                except KeyError:
                    pass
            else:
                ### extract PK from data:
                objid = []
                for entry in data:
                    new_entry = {field: entry[field] for field in self.pk}
                    objid.append(new_entry)
                return objid
        else:
            return self.error(
                reason=f"Invalid PK definition for {self.__name__}: {self.pk}",
                status=410
            )

    async def _get_data(self, qp, args):
        """_get_data.

        Get and pre-processing POST data before use it.
        """
        db = self.request.app["database"]
        conn = None
        data = None
        ## getting first the id from params or data:
        try:
            objid = self.get_primary(args)
        except (TypeError, KeyError):
            objid = None
        try:
            async with await db.acquire() as conn:
                self.get_model.Meta.connection = conn
                if objid is not None:
                    try:
                        if isinstance(self.pk, list):
                            return await self.get_model.get(**objid)
                        args = {self.pk: objid}
                        if isinstance(objid, list):
                            return await self.model.filter(**args)
                        else:
                            return await self.model.get(**args)
                    except NoDataFound:
                        return None
                elif len(qp) > 0:
                    print("FILTER")
                    query = await self.get_model.filter(**qp)
                elif len(args) > 0:
                    print("GET BY ARGS")
                    query = await self.get_model.get(**args)
                    return query.dict()
                else:
                    print("ALL")
                    query = await self.get_model.all()
                if query:
                    data = [row.dict() for row in query]
                else:
                    raise NoDataFound(
                        'No Data was found'
                    )
        except NoDataFound:
            raise
        except Exception as err:
            raise NavException(
                f"Error getting data from Model: {err}"
            ) from err
        finally:
            ## we don't need the ID
            self.get_model.Meta.connection = None
            await db.release(conn)
        return data

    @service_auth
    async def head(self):
        """Getting Model information."""
        # await self.session()
        ## calculating resource:
        response = self.model.schema(as_dict=True)
        columns = list(response["properties"].keys())
        size = len(str(response))
        headers = {
            "Content-Length": size,
            "X-Columns": f"{columns!r}",
            "X-Model": self.model.__name__,
            "X-Tablename": self.model.Meta.name,
        }
        return self.no_content(headers=headers)

    @service_auth
    async def get(self):
        """GET Model information."""
        args, meta, qp, fields = self.get_parameters()
        try:
            if meta == ":meta":
                # returning JSON schema of Model:
                response = self.model.schema(as_dict=True)
                return self.json_response(response)
            elif meta == ':sample':
                # return a JSON sample of data:
                response = self.model.sample()
                return self.json_response(response)
        except KeyError:
            pass
        try:
            data = await self._get_data(qp, args)
            return await self._model_response(data, fields=fields)
        except ModelError as ex:
            error = {
                "error": f"Missing Info for Model {self.name}",
                "payload": str(ex)
            }
            return self.error(response=error, status=400)
        except ValidationError as ex:
            error = {
                "error": f"Unable to load {self.__name__} info from Database",
                "payload": ex.payload,
            }
            return self.error(response=error, status=400)
        except NoDataFound:
            headers = {
                "X-STATUS": "EMPTY",
                "X-MESSAGE": f"Data on {self.__name__} not Found",
            }
            return self.no_content(headers=headers)
        except TypeError as ex:
            error = {
                "error": f"Invalid payload for {self.name}",
                "payload": str(ex),
            }
            return self.error(response=error, status=406)
        except (DriverError, ProviderError, RuntimeError) as ex:
            error = {
                "error": "Database Error",
                "payload": str(ex),
            }
            return self.critical(response=error, status=500)

    async def _post_data(self, *args, **kwargs) -> Any:
        """_post_data.

        Get and pre-processing POST data before use it.
        """
        async def set_column_value(value):
            for name, column in self.model.get_columns().items():
                ### if a function with name _get_{column name} exists
                ### then that function is called for getting the field value
                if hasattr(self, f'_get_{name}'):
                    fn = getattr(self, f'_get_{name}')
                    try:
                        val = value.get(name, None)
                    except AttributeError:
                        val = None
                    value[name] = await fn(
                        value=val,
                        column=column,
                        data=value,
                        *args, **kwargs
                    )
        try:
            data = await self.json_data()
        except ValueError:
            return None
            if isinstance(data, list):
                for element in data:
                    await set_column_value(element)
            elif isinstance(data, dict):
                    await set_column_value(data)
            else:
                self.error(
                    reason=f"Invalid Data Format: {type(data)}", status=400
                )
        except (TypeError, AttributeError) as ex:
            self.error(
                reason=f"Invalid {self.name} Data: {ex}", status=400
            )
        return data

    async def _patch_response(self, result, status: int = 202) -> web.Response:
        """_patch_data.

        Post-processing data after saved and before summit.
        """
        return self.json_response(result, status = status)

    @service_auth
    async def patch(self):
        """
        patch.
            summary: return the metadata from table or, if we got post
            realizes a partially atomic updated of the query.
        """
        args, meta, qp, fields = self.get_parameters()
        if meta == ':meta':
            ## returning the columns on Model:
            fields = self.model.__fields__
            return self.json_response(fields)
        data = await self._post_data()
        if data:
            ## patching data:
            db = self.request.app["database"]
            ## getting first the id from params or data:
            try:
                objid = self.get_primary(data)
            except (TypeError, KeyError):
                try:
                    objid = self.get_primary(params)
                except (TypeError, KeyError):
                    self.error(
                        response={"message": f"Invalid Data Primary Key: {self.name}"},
                        status=400
                    )
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                try:
                    if isinstance(objid, list):
                        result = []
                        for entry in data:
                            if isinstance(self.pk, str):
                                pk = [self.pk]
                            else:
                                pk = self.pk
                            _filter = {field: entry[field] for field in pk}
                            obj = await self.model.get(**_filter)
                            for key, val in entry.items():
                                if key in obj.get_fields():
                                    obj.set(key, val)
                            result.append(await obj.update())
                        return await self._patch_response(result, status=202)
                    else:
                        args = {self.pk: objid}
                        result = await self.model.get(**args)
                        for key, val in data.items():
                            if key in result.get_fields():
                                result.set(key, val)
                        result = await result.update()
                    return await self._patch_response(result, status=202)
                except NoDataFound:
                    headers = {"x-error": f"{self.__name__} was not Found"}
                    self.no_content(headers=headers)
                if not result:
                    headers = {"x-error": f"{self.__name__} was not Found"}
                    self.no_content(headers=headers)
        else:
            try:
                # getting metadata of Model
                data = {}
                for name, field in self.model.get_columns().items():
                    key = field.name
                    _type = field.db_type()
                    default = None
                    if field.default is not None:
                        default = f"{field.default!r}"
                    data[key] = {"type": _type, "default": default}
                return await self._model_response(data, fields=fields)
            except Exception as err:  # pylint: disable=W0703
                print(err)
                stack = traceback.format_exc()
                return self.critical(
                    exception=err, stacktrace=stack
                )

    async def _post_response(self, result, status: int = 200) -> web.Response:
        """_post_data.

        Post-processing data after saved and before summit.
        """
        return self.json_response(result, status = status)

    @service_auth
    async def put(self):
        """ "
        put.
           summary: insert a row in table
        """
        args, meta, qp, fields = self.get_parameters()
        data = await self._post_data()
        if not data:
            return self.error(
                response={"error": "Cannot Insert a row without data"},
                state=406,
            )
        ## validate directly with model:
        if isinstance(data, list):
            ## Bulk Insert
            db = self.request.app["database"]
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                try:
                    result = await self.model.create(data)
                    return await self._post_response(result, status=201)
                except DriverError as ex:
                    return self.error(
                        response={"message": f"Bulk Insert Error", "error": str(ex.message)},
                        status=410,
                    )
        try:
            parameters = {**qp, **data}
        except TypeError:
            parameters = data
        try:
            resultset = self.model(**parameters)  # pylint: disable=E1102
            if not resultset.is_valid():
                return self.error(
                    response=f"Invalid data for Schema {self.__name__}"
                )
            db = self.request.app["database"]
            async with await db.acquire() as conn:
                resultset.Meta.connection = conn
                result = await resultset.insert()
                return await self._post_response(result, status=201)
        except StatementError as ex:
            error = {
                "message": f"Cannot Insert, duplicated {self.__name__}",
                "error": str(ex)
            }
            return self.error(response=error, status=400)
        except ModelError as ex:
            error = {
                "message": f"Unable to insert {self.__name__}",
                "error": str(ex)
            }
            return self.error(response=error, status=400)
        except ValidationError as ex:
            error = {
                "error": f"Unable to insert {self.__name__} info",
                "payload": ex.payload,
            }
            return self.error(response=error, status=400)
        except (TypeError, AttributeError, ValueError) as ex:
            error = {
                "error": f"Invalid payload for {self.__name__}",
                "payload": str(ex),
            }
            return self.error(response=error, status=406)

    @service_auth
    async def post(self):
        """
        post.
            summary: update (or create) a row in Model
        """
        args, meta, qp, fields = self.get_parameters()
        data = await self._post_data()
        if not data:
            return self.error(
                response={"error": "Cannot Insert a row without data"},
                state=406,
            )
        db = self.request.app["database"]
        # updating several at the same time:
        if isinstance(data, list):
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # mass-update using arguments:
                result = []
                for entry in data:
                    if isinstance(self.pk, str):
                        pk = [self.pk]
                    else:
                        pk = self.pk
                    try:
                        _filter = {field: entry[field] for field in pk}
                    except KeyError:
                        continue
                    try:
                        obj = await self.model.get(**_filter)
                        print('OBJ ', obj)
                        ## saved with new changes:
                        for key, val in entry.items():
                            if key in obj.get_fields():
                                obj.set(key, val)
                        r = await obj.update()
                        result.append(r)
                    except ModelError as ex:
                        error = {
                            "message": f"Invalid {self.__name__}",
                            "error": str(ex),
                        }
                        return self.error(response=error, status=406)
                return await self._model_response(
                    result,
                    status=202,
                    fields=fields
                )
        else:
            objid = None
            try:
                objid = self.get_primary(data)
            except (TypeError, KeyError):
                try:
                    objid = self.get_primary(params)
                except (TypeError, KeyError) as ex:
                    self.error(
                        response={
                            "message": f"Invalid Data Primary Key: {self.__name__}",
                            "error": f"Value: {ex}"
                        },
                        status=400
                    )
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                error = {"error": f"{self.__name__} was not Found"}
                if isinstance(objid, list):
                    try:
                        result = await self.model.updating(_filter=objid, **data)
                        return await self._model_response(result, status=202, fields=fields)
                    except ModelError as ex:
                        error = {
                            "error": f"Missing Info for Model {self.__name__}",
                            "payload": str(ex)
                        }
                        return self.error(response=error, status=400)
                else:
                    try:
                        args = {self.pk: objid}
                        result = await self.model.get(**args)
                    except ModelError as ex:
                        error = {
                            "error": f"Missing Info for Model {self.__name__}",
                            "payload": str(ex)
                        }
                        return self.error(response=error, status=400)
                    except NoDataFound:
                        ### need to created:
                        qry = self.model(**data)
                        if qry.is_valid():
                            result = await qry.insert()
                            return await self._model_response(
                                result,
                                status=201,
                                fields=fields
                            )
                        else:
                            return self.error(
                                response=f"Unable to Insert {self.__name__}",
                            )
                    ## saved with new changes:
                    for key, val in data.items():
                        if key in result.get_fields():
                            result.set(key, val)
                    try:
                        data = await result.update()
                    except ModelError as ex:
                        error = {
                            "message": f"Invalid {self.__name__}",
                            "error": str(ex),
                        }
                        return self.error(response=error, status=406)
                    except ValidationError as ex:
                        error = {
                            "error": f"Unable to insert {self.__name__} info",
                            "payload": str(ex.payload),
                        }
                        return self.error(response=error, status=400)
                    except (TypeError, AttributeError, ValueError) as ex:
                        error = {
                            "error": f"Invalid payload for {self.__name__}",
                            "payload": str(ex),
                        }
                        return self.error(response=error, status=406)
                    return await self._model_response(data, status=202, fields=fields)

    async def _del_data(self, *args, **kwargs) -> Any:
        """_get_data.

        Get and pre-processing POST data before use it.
        """
        data = {}
        try:
            data = await self.json_data()
            for name, column in self.model.get_columns().items():
                ### if a function with name _get_{column name} exists
                ### then that function is called for getting the field value
                if hasattr(self, f'_get_{name}'):
                    fn = getattr(self, f'_get_{name}')
                    try:
                        val = data.get(name, None)
                    except AttributeError:
                        val = None
                    if callable(fn):
                        data[name] = await fn(
                            value=val,
                            column=column,
                            data=data,
                            *args, **kwargs
                        )
        except (TypeError, ValueError, NavException):
            pass
        return data

    @service_auth
    async def delete(self):
        """ "
        delete.
           summary: delete a table object
        """
        args, meta, qp, fields = self.get_parameters()
        data = await self._del_data()
        try:
            objid = self.get_primary(data)
        except (TypeError, KeyError):
            try:
                objid = self.get_primary(args)
            except (TypeError, KeyError):
                objid = None
        db = self.request.app["database"]
        if objid:
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                try:
                    if isinstance(objid, list):
                        data = []
                        for entry in objid:
                            args = {self.pk: entry}
                            obj = await self.model.get(**args)
                            data.append(await obj.delete())
                    else:
                        if isinstance(self.pk, list):
                            result = await self.model.get(**objid)
                        else:
                            args = {self.pk: objid}
                            # Delete them this Client
                            result = await self.model.get(**args)
                        data = await result.delete()
                    return await self._model_response(data, status=202)
                except NoDataFound:
                    error = {
                        "message": f"Key {objid} was not found on {self.__name__}",
                    }
                    return self.error(response=error, status=404)
        else:
            if len(qp) > 0:
                async with await db.acquire() as conn:
                    self.model.Meta.connection = conn
                    result = await self.model.remove(**qp)
                    return await self._model_response(result, status=202)
            else:
                self.error(
                    reason=f"Cannot Delete {self.__name__} with Empy Query",
                    status=400
                )
