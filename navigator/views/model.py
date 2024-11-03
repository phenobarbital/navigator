from collections.abc import Awaitable
from typing import Optional, Union, Any
import importlib
import asyncio
from aiohttp import web
from navconfig.logging import logger
from datamodel import BaseModel
from datamodel.abstract import ModelMeta
from datamodel.converters import parse_type
from datamodel.exceptions import ValidationError
from asyncdb.models import Model
from asyncdb.exceptions import (
    ProviderError,
    DriverError,
    NoDataFound,
    ModelError,
    StatementError
)
from navigator.exceptions import (
    ConfigError
)
from .abstract import AbstractModel, NotSet


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
    except Exception as err:  # pylint: disable=W0703
        logger.error(
            f"Error loading Model {tablename}: {err!s}"
        )


class ModelView(AbstractModel):
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
    model_name: str = None  # Override the current model with other.
    path: str = None
    pk: Union[str, list] = None
    _required: list = []
    _primaries: list = []
    _hidden: list = []
    # New Callables to be used on response:
    _get_callback: Optional[Awaitable] = None
    _put_callback: Optional[Awaitable] = None
    _post_callback: Optional[Awaitable] = None
    _patch_callback: Optional[Awaitable] = None
    _delete_callback: Optional[Awaitable] = None

    def __init__(self, request, *args, **kwargs):
        if self.model_name is not None:
            ## import Other Model from Variable
            self.model = self._import_model(self.model_name)
        if self.get_model and isinstance(self.get_model, str):
            self.get_model = self._import_model(self.get_model)
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

    def _import_model(self, model: str):
        try:
            parts = model.split(".")
            name = parts[-1]
            classpath = ".".join(parts[:-1])
            module = importlib.import_module(classpath, package=name)
            obj = getattr(module, name)
            return obj
        except ImportError:
            ## Using fallback Model
            return self.model

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
            # Model doesn't exists
            raise ConfigError(
                f"Model {self.__name__} Doesn't Exists"
            )

    async def _model_response(
            self,
            response: Any,
            fields: list = None,
            headers: dict = None,
            status: int = 200
    ) -> web.Response:
        # TODO: passing query Search
        if response is None:
            return self.no_content(headers=headers)
        if not response:
            return self.error(
                response={
                    "error": f"Record for {self.__name__} not Found"
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
        response = self.json_response(
            result,
            headers=headers,
            status=status
        )
        # calling a callback into a send-and-forget response:
        loop = asyncio.get_event_loop()
        if callable(self._get_callback):
            try:
                # Run the coroutine in a new thread
                asyncio.run_coroutine_threadsafe(
                    self._get_callback(response, result),
                    loop
                )
            except Exception as ex:
                self.logger.warning(
                    f"Error in _get_callback: {ex}"
                )
        return response

    _get_response = _model_response  # alias

    def get_primary(self, data: dict, args: dict = None) -> Any:
        """get_primary.
            Get Primary Id from Parameters.
        """
        objid = None
        if self.pk is None:
            ### discover the primary keys of Model.
            primary_keys = []
            for key, field in self.model.get_columns().items():
                if field.primary_key:
                    primary_keys.append(key)
            self.pk = primary_keys
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
                except (TypeError, KeyError) as ex:
                    print(ex)
                    try:
                        objid = data["id"]
                        if objid == '':
                            objid = None
                    except KeyError:
                        raise
                ## but if objid has /
                if isinstance(objid, str):
                    if '/' in objid:
                        return objid.split('/')
                return objid
        elif isinstance(self.pk, list):
            if isinstance(data, dict):
                if 'id' in data:
                    try:
                        args = {}
                        paramlist = [item.strip() for item in data["id"].split("/") if item.strip()]
                        if not paramlist:
                            return None
                        if len(paramlist) != len(self.pk):
                            if len(self.pk) == 1:
                                # find various:
                                args[self.pk[0]] = paramlist
                                return args
                            return self.error(
                                response={
                                    "message": f"Wrong Number of Args in PK: {self.pk}",
                                    "description": f"{paramlist!r}",
                                },
                                status=410,
                            )
                        for key in self.pk:
                            col = self.model.__columns__[key]
                            _type = col.type
                            if isinstance(_type, ModelMeta):
                                try:
                                    _type = _type.__columns__[key].type
                                except (TypeError, AttributeError, KeyError) as ex:
                                    _type = str
                            else:
                                _type = col.type
                            if _type == int:
                                try:
                                    val = int(paramlist.pop(0))
                                except ValueError:
                                    val = paramlist.pop(0)
                            else:
                                # TODO: use validation from datamodel
                                # evaluate the corrected type for fields:
                                val = paramlist.pop(0)
                            args[key] = val
                        return args
                    except KeyError:
                        pass
                else:
                    objid = {field: data[field] for field in self.pk}
            elif isinstance(data, list):
                objid = []
                for entry in data:
                    new_entry = {field: entry[field] for field in self.pk}
                    objid.append(new_entry)
            return objid
        else:
            raise ValueError(
                f"Invalid PK definition for {self.__name__}: {self.pk}"
            )

    async def _get_primary_data(self, args):
        try:
            objid = self.get_primary(args)
        except (TypeError, KeyError):
            objid = None
        return objid

    async def _get_data(self, qp, args):
        """_get_data.

        Get and pre-processing GET data before use it.
        """
        conn = None
        data = None
        pagination: bool = False
        page = None
        size = 1000

        # Default pagination Method:
        if pagination := qp.get('paginate', False) is True:
            page = qp.get('page', 1)
            size = qp.get('size', 1000)

        ## getting first primary IDs for filtering:
        _primary = await self._get_primary_data(args)

        async def _get_filters():
            value = {}
            for name, column in self.model.get_columns().items():
                ### if a function with name _filter_{column name} exists
                ### then that function is called for filtering the field value
                fn = getattr(self, f'_filter_{name}', None)
                if fn:
                    try:
                        val = value.get(name, None)
                    except AttributeError:
                        val = None
                    try:
                        value[name] = await fn(
                            value=val,
                            column=column,
                            data=value
                        )
                    except NotSet:
                        return
            return value
        _filter = await _get_filters()
        # TODO: Add Filter Function
        try:
            async with await self.handler(request=self.request) as conn:
                self.get_model.Meta.connection = conn
                if _primary is not None:
                    if isinstance(_primary, list):
                        args = {self.pk: _primary}
                        return await self.get_model.filter(**args, **_filter)
                    elif isinstance(_primary, dict):
                        _filter = {**_filter, **_primary}
                        res = await self.get_model.filter(**_filter)
                        if len(res) == 1:
                            return res[0]
                        return res
                    else:
                        if isinstance(self.pk, list):
                            res = await self.get_model.filter(**_primary)
                            if len(res) == 1:
                                return res[0]
                            return res
                        args = {self.pk: _primary}
                        args = {**_filter, **args}
                        return await self.get_model.get(**args)
                elif len(qp) > 0:
                    print("FILTER")
                    query = await self.get_model.filter(**qp, **_filter)
                elif len(args) > 0:
                    print("GET BY ARGS")
                    if _filter:
                        args = {**_filter, **args}
                    query = await self.get_model.get(**args)
                    return query.to_dict()
                else:
                    if _filter:
                        query = await self.get_model.filter(**_filter)
                    else:
                        print("ALL")
                        query = await self.get_model.all()
                if query:
                    data = [row.to_dict() for row in query]
                else:
                    raise NoDataFound(
                        'No Data was found'
                    )
        except ValidationError:
            raise
        except NoDataFound:
            raise
        except Exception as err:
            raise ModelError(
                f"{err}"
            ) from err
        finally:
            ## we don't need the ID
            self.get_model.Meta.connection = None
        return data

    async def _filtering(self, queryparams: dict) -> web.Response:
        # Making a filter based on field received.
        filter_param = queryparams.get('_filter')
        if filter_param:
            # Split the filter parameter into field and value
            field, value = filter_param.split('=')
            # Get the table and schema names
            table_name = self.get_model.Meta.name
            schema_name = self.get_model.Meta.schema
            # TODO: discover the field type from Model.
            ftype = self.get_model.column(field)
            # Build the SQL query
            query = f"""
            SELECT {field} FROM {schema_name}.{table_name}
            WHERE {field} LIKE '{value}%'"""
            async with await self.handler(request=self.request) as conn:
                result, error = await conn.query(query)
                if error:
                    self.logger.warning(
                        f"Unable to filter by criteria {filter_param}"
                    )
                    return None
                return self.json_response(
                    result,
                    status=200
                )
        else:
            return None

    @service_auth
    async def get(self):
        """GET Model information."""
        if not await self._pre_get():
            return self.error(
                response={
                    "message": f"{self.__name__} Error on Pre-Validation"
                },
                status=412
            )
        args, meta, qp, fields = self.get_parameters()
        response = await self._get_meta_info(meta, fields)
        if response is not None:
            return response
        try:
            # Add Filtering
            response = await self._filtering(qp)
            if response is not None:
                return response
            # TODO: Add Query
            # TODO: Add Pagination (offset, limit)
            data = await self._get_data(qp, args)
            return await self._model_response(data, fields=fields)
        except ModelError as ex:
            error = {
                "error": f"{self.__name__} Error",
                "payload": str(ex)
            }
            return self.error(
                response=error, status=400
            )
        except ValidationError as ex:
            error = {
                "error": f"{ex}",
                "payload": f"{ex.payload!r}",
            }
            return self.error(
                response=error, status=400
            )
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
                fn = getattr(self, f'_set_{name}', None)
                if not fn:
                    fn = getattr(self, f'_get_{name}', None)
                    if fn:
                        raise DeprecationWarning(
                            f"Method _get_{name} is deprecated. "
                            f"Use _set_{name} instead."
                        )
                if fn:
                    try:
                        val = value.get(name, None)
                    except AttributeError:
                        val = None
                    try:
                        value[name] = await fn(
                            value=val,
                            column=column,
                            data=value,
                            *args, **kwargs
                        )
                    except NotSet:
                        return
        data = await self.json_data()
        if isinstance(data, list):
            for element in data:
                await set_column_value(element)
        elif isinstance(data, dict):
            await set_column_value(data)
        else:
            try:
                data = await self.body()
            except ValueError:
                data = None
        return data

    async def _patch_response(self, result, status: int = 202) -> web.Response:
        """_patch_data.

        Post-processing data after saved and before summit.
        """
        response = self.json_response(result, status=status)
        # calling a callback into a send-and-forget response:
        loop = asyncio.get_event_loop()
        if callable(self._patch_callback):
            try:
                # Run the coroutine in a new thread
                asyncio.run_coroutine_threadsafe(
                    self._patch_callback(response, result),
                    loop
                )
            except Exception as ex:
                self.logger.warning(
                    f"Error in _patch_callback: {ex}"
                )
        return response

    def required_by_put(self):
        return []

    def required_by_patch(self):
        return []

    def required_by_post(self):
        return []

    def _is_required(self, required: list, data: Union[dict, list]):
        if not required:
            return []
        else:
            if isinstance(data, dict):
                return [f for f in required if f not in data.keys()]
            elif isinstance(data, list):
                return [f for f in required if f not in data[0].keys()]
            elif isinstance(data, BaseModel):
                return [f for f in required if f not in data.get_fields()]
            else:
                raise TypeError(
                    "Expected DATA to be a dict or list"
                )

    def get_patch_attribute(self, args: dict):
        if 'id' in args:
            try:
                _attrs = args['id'].split('/')
                args['id'] = _attrs[0]
                return args, _attrs[1]
            except IndexError:
                pass
        return args, None

    async def _calculate_column(
        self,
        name: str,
        value: str,
        column: Any,
        data: Any = None,
        **kwargs
    ):
        """ Check if a function with name _calculate_{column name} exists
        then that function is called for getting the field value """
        fn = getattr(self, f'_calculate_{name}', None)
        if not fn:
            return
        try:
            return await fn(
                value=value,
                column=column,
                data=data,
                **kwargs
            )
        except NotSet:
            return

    async def _set_update(self, model, data):
        for key, val in data.items():
            if key in model.get_fields():
                col = model.column(key)
                if (
                    newval := await self._calculate_column(
                        name=key,
                        value=val,
                        column=col,
                        data=data
                    )
                ):
                    model.set(key, newval)
                    continue
                try:
                    newval = parse_type(col.type, val)
                except ValueError:
                    if col.type == str:
                        newval = str(val)
                    else:
                        newval = val
                model.set(key, newval)

    async def _patch_data(self, *args, **kwargs) -> Any:
        """_patch_data.

        Get and pre-processing PATCH data before use it.
        """
        async def set_column_value(value):
            for name, column in self.model.get_columns().items():
                ### if a function with name _get_{column name} exists
                ### then that function is called for getting the field value
                fn = getattr(self, f'_set_{name}', None)
                if not fn:
                    fn = getattr(self, f'_patch_{name}', None)
                if fn:
                    try:
                        val = value.get(name, None)
                    except AttributeError:
                        val = None
                    try:
                        value[name] = await fn(
                            value=val,
                            column=column,
                            data=value,
                            *args, **kwargs
                        )
                    except NotSet:
                        return
        data = await self.json_data()
        if isinstance(data, list):
            for element in data:
                await set_column_value(element)
        elif isinstance(data, dict):
            await set_column_value(data)
        else:
            try:
                data = await self.body()
            except ValueError:
                data = None
        return data

    @service_auth
    async def patch(self):
        """
        patch.
            summary: return the metadata from table or, if we got post
            realizes a partially atomic updated of the query.
        """
        if not await self._pre_patch():
            return self.error(
                response={
                    "message": f"{self.__name__} Error on Pre-Validation"
                },
                status=412
            )
        args, meta, _, fields = self.get_parameters()
        if isinstance(self.pk, str):
            ## Allowing passing the Attribute in the URL
            args, _attribute = self.get_patch_attribute(args)
        else:
            _attribute = None
        if meta == ':meta':
            ## returning the columns on Model:
            fields = self.model.__fields__
            return self.json_response(fields)
        data = await self._patch_data()
        if not data:
            headers = {"x-error": f"{self.__name__} POST data Missing"}
            self.error(
                response={
                    "message": f"{self.__name__} POST data Missing"
                },
                headers=headers,
                status=412
            )
        ### validation if data is covered by required columns
        try:
            if (required := self._is_required(self.required_by_patch(), data)):
                self.error(
                    response={
                        "message": f"Missing required: {', '.join(required)}"
                    },
                    status=412
                )
        except TypeError as exc:
            self.error(
                response={"Validation Error": str(exc)},
                status=400
            )
        ## patching data:
        ## getting first the id from params or data:
        if isinstance(data, str):
            objid = self.get_primary(args)
        else:
            try:
                objid = self.get_primary(data)
            except (TypeError, KeyError, ValueError):
                try:
                    objid = self.get_primary(args)
                except (TypeError, KeyError, ValueError) as err:
                    self.error(
                        response={
                            "message": f"Invalid Primary Key: {self.__name__}",
                            "error": str(err)
                        },
                        status=400
                    )
        try:
            async with await self.handler(request=self.request) as conn:
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
                            await self._set_update(obj, entry)
                            result.append(await obj.update())
                        return await self._patch_response(result, status=202)
                    else:
                        if isinstance(self.pk, list):
                            if any(key in data for key in self.pk):
                                ## Data is trying to change the Primary Key:
                                try:
                                    obj = await self.model.get(**objid)
                                    await self._set_update(obj, data)
                                    result = await self.model.updating(
                                        _filter=objid, **obj.to_dict()
                                    )
                                    return await self._patch_response(
                                        result,
                                        status=202
                                    )
                                except (NoDataFound, DriverError) as ex:
                                    headers = {
                                        "x-error": f"{self.__name__}:{objid} was not Found",
                                        "x-message": str(ex)
                                    }
                                    return self.no_content(headers=headers)
                                except Exception as ex:
                                    print(ex)
                            obj = await self.model.get(**objid)
                        else:
                            args = {self.pk: objid}
                            obj = await self.model.get(**args)
                        # Updating Object:
                        if isinstance(data, dict):
                            await self._set_update(obj, data)
                        else:
                            # Patching one Single Attribute:
                            if _attribute in obj.get_fields():
                                col = obj.column(_attribute)
                                newval = parse_type(col.type, data)
                                obj.set(_attribute, newval)
                        result = await obj.update()
                    return await self._patch_response(result, status=202)
                except NoDataFound:
                    headers = {"x-error": f"{self.__name__} was not Found"}
                    self.no_content(headers=headers)
                if not result:
                    headers = {"x-error": f"{self.__name__} was not Found"}
                    self.no_content(headers=headers)
        except Exception as ex:
            self.logger.exception(ex, stack_info=True)
            error = {
                "reason": f"Model {self.__name__} Error",
                "exception": ex,
                "payload": str(ex),
                "status": 500
            }
            return self.critical(
                **error
            )

    async def _post_response(self, result: BaseModel, status: int = 200, fields: list = None) -> web.Response:
        """_post_response.

        Post-processing data after saved and before summit.
        """
        response = self.json_response(result, status=status)
        # calling a callback into a send-and-forget response:
        loop = asyncio.get_event_loop()
        if callable(self._post_callback):
            try:
                # Run the coroutine in a new thread
                asyncio.run_coroutine_threadsafe(
                    self._post_callback(response, result),
                    loop
                )
            except Exception as ex:
                self.logger.warning(
                    f"Error in _post_callback: {ex}"
                )
        return response

    async def _put_response(self, result: BaseModel, status: int = 200, fields: list = None) -> web.Response:
        """_put_response.

        Post-processing data after saved and before summit.
        """
        response = self.json_response(result, status=status)
        # calling a callback into a send-and-forget response:
        loop = asyncio.get_event_loop()
        if callable(self._put_callback):
            try:
                # Run the coroutine in a new thread
                asyncio.run_coroutine_threadsafe(
                    self._put_callback(response, result),
                    loop
                )
            except Exception as ex:
                self.logger.warning(
                    f"Error in _put_callback: {ex}"
                )
        return response

    @service_auth
    async def put(self):
        """ "
        put.
           summary: replaces or insert a row in table
        """
        if not await self._pre_put():
            return self.error(
                response={
                    "message": f"{self.__name__} Error on Pre-Validation"
                },
                status=412
            )
        _, _, qp, fields = self.get_parameters()
        data = await self._post_data()
        if not data:
            return self.error(
                response={"error": "Cannot Insert a row without data"},
                state=406,
            )
        ### validation if data is covered by required columns
        try:
            if (required := self._is_required(self.required_by_put(), data)):
                self.error(
                    response={
                        "message": f"Missing required data: {', '.join(required)}",
                        "required": required
                    },
                    status=400
                )
        except TypeError as exc:
            self.error(
                response={"Validation error": str(exc)},
                status=400
            )
        ## validate directly with model:
        if isinstance(data, list):
            if isinstance(data[0], BaseModel):
                data = [d.to_dict() for d in data]
            ## Bulk Insert/Replace
            async with await self.handler(request=self.request) as conn:
                self.model.Meta.connection = conn
                try:
                    result = await self.model.create(data)
                    return await self._put_response(
                        result,
                        status=201,
                        fields=fields
                    )
                except DriverError as ex:
                    return self.error(
                        response={
                            "message": f"{self.__name__} Bulk Insert Error",
                            "error": str(ex)
                        },
                        status=410,
                    )
        try:
            if isinstance(data, BaseModel):
                data = data.to_dict()
            data = {**qp, **data}
        except TypeError:
            pass
        try:
            objid = self.get_primary(data)
        except (ValueError, KeyError):
            objid = {}
        try:
            async with await self.handler(request=self.request) as conn:
                # check if object exists:
                try:
                    if not objid:
                        raise NoDataFound(
                            "New Object"
                        )
                    if isinstance(self.pk, list):
                        _args = objid
                    else:
                        _args = {self.pk: objid}
                    self.model.Meta.connection = conn
                    obj = await self.model.get(**_args)
                    await self._set_update(obj, data)
                    result = await obj.update()
                    status = 202
                except NoDataFound:
                    # There is no data to update:
                    obj = self.model(**data)  # pylint: disable=E1102
                    obj.Meta.connection = conn
                    if not obj.is_valid():
                        return self.error(
                            response={
                                "message": f"Invalid data for {self.__name__}"
                            }
                        )
                    try:
                        result = await obj.insert()
                        status = 201
                    except DriverError as exc:
                        return self.error(
                            response={
                                "message": f"Unable to insert over {self.__name__}",
                                "error": str(exc)
                            }
                        )
                return await self._put_response(result, status=status, fields=fields)
        except NoDataFound as exc:
            return self.error(
                response={
                    "message": f"Unable to insert over {self.__name__}",
                    "error": str(exc)
                },
                status=404
            )
        except StatementError as ex:
            err = str(ex)
            if 'duplicate' in err:
                error = {
                    "message": f"Duplicated {self.__name__}",
                    "error": err
                }
            else:
                error = {
                    "message": f"Unable to insert over {self.__name__}",
                    "error": err
                }
            return self.error(response=error, status=400)
        except ModelError as ex:
            error = {
                "message": f"Unable to insert over {self.__name__}",
                "error": str(ex)
            }
            return self.error(response=error, status=400)
        except ValidationError as ex:
            error = {
                "error": f"Unable to insert over {self.__name__} info",
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
        if not await self._pre_post():
            return self.error(
                response={
                    "message": f"{self.__name__} Error on Pre-Validation"
                },
                status=412
            )
        args, _, _, fields = self.get_parameters()
        data = await self._post_data()
        if not data:
            return self.error(
                response={"error": "Cannot Insert a row without data"},
                state=406,
            )
        ### validation if data is covered by required columns
        try:
            if (required := self._is_required(self.required_by_post(), data)):
                self.error(
                    response={
                        "message": f"Missing required data: {', '.join(required)}",
                        "required": required
                    },
                    status=400
                )
        except TypeError as exc:
            self.error(
                response={"error": str(exc)},
                status=400
            )
        # updating several at the same time:
        if isinstance(data, list):
            async with await self.handler(request=self.request) as conn:
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
                        try:
                            obj = await self.model.get(**_filter)
                            await self._set_update(obj, entry)
                            r = await obj.update()
                            result.append(r)
                        except NoDataFound:
                            # Object doesn't exist, create it:
                            obj = self.model(**entry)  # pylint: disable=E1102
                            obj.Meta.connection = conn
                            if not obj.is_valid():
                                continue
                            try:
                                r = await obj.insert()
                                result.append(r)
                            except DriverError as exc:
                                return self.error(
                                    response={
                                        "message": f"Unable to insert over {self.__name__}",
                                        "error": str(exc)
                                    }
                                )
                    except ModelError as ex:
                        error = {
                            "message": f"Invalid {self.__name__}",
                            "error": str(ex),
                        }
                        return self.error(response=error, status=406)
                return await self._post_response(
                    result,
                    status=202,
                    fields=fields
                )
        else:
            objid = None
            if isinstance(data, BaseModel):
                data = data.to_dict()
            try:
                objid = self.get_primary(data)
            except (TypeError, KeyError):
                try:
                    objid = self.get_primary(args)
                except (TypeError, KeyError) as ex:
                    self.error(
                        response={
                            "message": f"Invalid Data Primary Key: {self.__name__}",
                            "error": f"Value: {ex}"
                        },
                        status=400
                    )
            async with await self.handler(request=self.request) as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                if isinstance(objid, list):
                    try:
                        result = await self.model.updating(_filter=objid, **data)
                        return await self._post_response(
                            result,
                            status=202,
                            fields=fields
                        )
                    except DriverError as exc:
                        return self.error(
                            response={
                                "message": f"Unable to insert over {self.__name__}",
                                "error": str(exc)
                            }
                        )
                    except ModelError as ex:
                        error = {
                            "error": f"Missing Info for Model {self.__name__}",
                            "payload": str(ex)
                        }
                        return self.error(response=error, status=400)
                else:
                    try:
                        if isinstance(self.pk, list):
                            args = objid
                        else:
                            args = {self.pk: objid}
                        # Getting the Object:
                        result = await self.model.get(**args)
                        ## saved with new changes:
                        await self._set_update(result, data)
                        result = await self.model.updating(
                            _filter=args, **result.to_dict()
                        )
                        return await self._post_response(
                            result,
                            status=202,
                            fields=fields
                        )
                    except Exception as exc:
                        print(exc, type(exc))
                    except NoDataFound:
                        ### need to created:
                        qry = self.model(**data)
                        if qry.is_valid():
                            try:
                                result = await qry.insert()
                            except DriverError as exc:
                                return self.error(
                                    response={
                                        "message": f"Unable to Insert over {self.__name__}",
                                        "error": str(exc),
                                    },
                                    status=406
                                )
                            return await self._post_response(
                                result,
                                status=201,
                                fields=fields
                            )
                        else:
                            return self.error(
                                response=f"Unable to Insert over {self.__name__}",
                            )
                    except ModelError as ex:
                        error = {
                            "error": f"Missing Info for Model {self.__name__}",
                            "payload": str(ex)
                        }
                        return self.error(response=error, status=400)
                    except DriverError as ex:
                        error = {
                            "message": f"{self.__name__} already exists",
                            "error": str(ex),
                        }
                        return self.error(response=error, status=406)
                    except ValidationError as ex:
                        error = {
                            "error": f"Unable to insert over {self.__name__} info",
                            "payload": str(ex.payload),
                        }
                        return self.error(response=error, status=400)

    async def _del_data(self, *args, **kwargs) -> Any:
        """_del_data.

        Get and pre-processing DELETE data before use it.
        """
        async def set_column_value(value):
            for name, column in self.model.get_columns().items():
                ### if a function with name _get_{column name} exists
                ### then that function is called for getting the field value
                fn = getattr(self, f'_del_{name}', None)
                if not fn:
                    fn = getattr(self, f'_set_{name}', None)
                if fn:
                    try:
                        val = value.get(name, None)
                    except AttributeError:
                        val = None
                    try:
                        value[name] = await fn(
                            value=val,
                            column=column,
                            data=value,
                            *args, **kwargs
                        )
                    except NotSet:
                        return
        data = await self.json_data()
        if isinstance(data, list):
            for element in data:
                await set_column_value(element)
        elif isinstance(data, dict):
            await set_column_value(data)
        else:
            try:
                data = await self.body()
            except ValueError:
                data = None
        return data

    async def _delete_response(self, result, status: int = 200) -> web.Response:
        """_delete_response.

        Post-processing data after deleted and before summit.
        """
        return self.json_response(result, status=status)

    def _del_primary(self, args: dict = None) -> Any:
        """_del_primary.
            Get Primary Id from Parameters for DELETE method
        """
        objid = None
        if self.pk is None:
            ### discover the primary keys of Model.
            primary_keys = []
            for key, field in self.model.get_columns().items():
                if field.primary_key:
                    primary_keys.append(key)
            self.pk = primary_keys
        if isinstance(self.pk, str):
            objid = args.get('id', None)
            return objid
        elif isinstance(self.pk, list):
            if isinstance(args, dict):
                if 'id' in args:
                    try:
                        _args = {}
                        paramlist = [
                            item.strip() for item in args["id"].split("/") if item.strip()
                        ]
                        if not paramlist:
                            return None
                        if len(paramlist) != len(self.pk):
                            if len(self.pk) == 1:
                                # find various:
                                _args[self.pk[0]] = paramlist
                                return _args
                            return self.error(
                                response={
                                    "message": f"Wrong Number of Args in PK: {self.pk}",
                                    "description": f"{paramlist!r}",
                                },
                                status=410,
                            )
                        for key in self.pk:
                            col = self.model.__columns__[key]
                            _type = col.type
                            if isinstance(_type, ModelMeta):
                                try:
                                    _type = _type.__columns__[key].type
                                except (TypeError, AttributeError, KeyError):
                                    _type = str
                            else:
                                _type = col.type
                            if _type == int:
                                try:
                                    val = int(paramlist.pop(0))
                                except ValueError:
                                    val = paramlist.pop(0)
                            else:
                                # TODO: use validation from datamodel
                                # evaluate the corrected type for fields:
                                val = paramlist.pop(0)
                            args[key] = val
                        return args
                    except KeyError:
                        pass
                else:
                    objid = {field: args[field] for field in self.pk}
            elif isinstance(args, list):
                objid = []
                for entry in args:
                    new_entry = {field: entry[field] for field in self.pk}
                    objid.append(new_entry)
            return objid
        else:
            raise ValueError(
                f"Invalid PK definition for {self.__name__}: {self.pk}"
            )

    @service_auth
    async def delete(self):
        """ "
        delete.
           summary: delete a table object
        """
        if not await self._pre_delete():
            return self.error(
                response={
                    "message": f"{self.__name__} Error on Pre-Validation"
                },
                status=412
            )
        args, _, qp, _ = self.get_parameters()
        if hasattr(self, '_del_primary_data'):
            objid = await self._del_primary_data(args)
        else:
            try:
                objid = self._del_primary(args)
            except (TypeError, KeyError) as exc:
                print(f'DEL Error: {exc}')
                objid = None
        if objid:
            async with await self.handler(request=self.request) as conn:
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
                            data = await result.delete(_filter=objid)
                        else:
                            args = {
                                self.pk: objid
                            }
                            # Delete them this Client
                            result = await self.model.get(**args)
                            data = await result.delete(_filter=args)
                    return await self._delete_response(data, status=202)
                except DriverError as exc:
                    error = {
                        "message": f"Error on {self.__name__}",
                        "error": str(exc)
                    }
                    return self.error(response=error, status=404)
                except NoDataFound:
                    error = {
                        "message": f"{objid} was not found on {self.__name__}",
                    }
                    return self.error(response=error, status=404)
        else:
            data = await self._del_data()
            if isinstance(data, list):
                # Bulk Delete by Post
                results = []
                async with await self.handler(request=self.request) as conn:
                    self.model.Meta.connection = conn
                    for entry in data:
                        objid = self.get_primary(entry)
                        if isinstance(self.pk, list):
                            result = await self.model.get(**objid)
                        else:
                            args = {
                                self.pk: objid
                            }
                            # Delete them this Client
                            try:
                                result = await self.model.get(**args)
                            except NoDataFound:
                                continue
                        try:
                            rst = await result.delete()
                            result = {
                                "deleted": rst,
                                "data": objid
                            }
                            results.append(result)
                        except Exception:
                            continue
                return await self._delete_response(results, status=202)
            elif data is not None:
                # delete with data.
                try:
                    objid = self.get_primary(data)
                except KeyError:
                    objid = None
                try:
                    async with await self.handler(request=self.request) as conn:
                        self.model.Meta.connection = conn
                        if objid:
                            try:
                                if isinstance(self.pk, list):
                                    args = objid
                                else:
                                    args = {
                                        self.pk: objid
                                    }
                                # Delete them this Client
                                result = await self.model.get(**args)
                                data = await result.delete(_filter=objid)
                            except DriverError as exc:
                                return await self._delete_response(
                                    {
                                        "error": f"Error on {self.__name__}",
                                        "message": str(exc)
                                    },
                                    status=400
                                )
                            except NoDataFound:
                                return await self._delete_response(
                                    {
                                        "error": f"{self.__name__} Not Found"
                                    },
                                    status=404
                                )
                        else:
                            # Using a payload for deleting using arguments
                            try:
                                objid = data
                                data = await self.model.remove(**data)
                            except NoDataFound:
                                return await self._delete_response(
                                    {
                                        "error": f"{self.__name__} Not Found"
                                    },
                                    status=404
                                )
                        result = {
                            "deleted": data,
                            "data": objid
                        }
                        return await self._delete_response(result, status=202)
                except (TypeError, KeyError, ValueError) as exc:
                    error = {
                        "message": f"We don't found POST data for deletion on {self.__name__}, exc",
                    }
                    return self.error(
                        response=error,
                        status=404
                    )
            if len(qp) > 0:
                async with await self.handler(request=self.request) as conn:
                    self.model.Meta.connection = conn
                    result = await self.model.remove(**qp)
                    result = {
                        "deleted": result
                    }
                    return await self._delete_response(result, status=202)
            else:
                self.error(
                    reason=f"Cannot Delete {self.__name__} with Empy Query",
                    status=400
                )
