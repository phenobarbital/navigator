from typing import Any, Optional, Union
from aiohttp import web
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from asyncdb.exceptions import (
    ProviderError,
    DriverError,
    NoDataFound,
    ModelError,
    StatementError
)
from navigator_session import get_session
from ..exceptions import NavException
from .base import BaseView


class ModelHandler(BaseView):
    model: BaseModel = None
    name: str = "Model"
    pk: Union[str, list] = "id"

    async def session(self):
        self._session = None
        try:
            self._session = await get_session(self.request)
        except (ValueError, RuntimeError) as err:
            return self.critical(
                reason="Error Decoding Session", request=self.request, exception=err
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
                response={"message": "Unauthorized"},
                status=403
            )
        return self._session

    async def get_userid(self, session, idx: str = 'user_id') -> int:
        if not session:
            self.error(
                reason="Unauthorized",
                status=403
            )
        try:
            if 'session' in session:
                return session['session'][idx]
            else:
                return session[idx]
        except KeyError:
            self.error(reason="Unauthorized", status=403)

    async def head(self):
        """Getting Client information."""
        await self.session()
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

    async def _post_get(self, result: Any, fields: list[str] = None) -> web.Response:
        """_post_get.

        Extensible for post-processing the GET response.
        """
        if not result:
            return self.no_content()
        else:
            if fields is not None:
                if isinstance(result, list):
                    new = []
                    for r in result:
                        row = {}
                        for field in fields:
                            row[field] = getattr(r, field, None)
                        new.append(row)
                    result = new
                else:
                    ## filtering result to returning only fields asked:
                    result = {}
                    for field in fields:
                        result[field] = getattr(result, field, None)
            return self.json_response(result)

    async def _get_object_by_id(self, idx: Any) -> BaseModel:
        db = self.request.app["database"]
        conn = None
        try:
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                # look for this client, after, save changes
                try:
                    if isinstance(self.pk, list):
                        return await self.model.get(**idx)
                    args = {self.pk: idx}
                    if isinstance(idx, list):
                        return await self.model.filter(**args)
                    else:
                        return await self.model.get(**args)
                except NoDataFound:
                    return None
        except Exception as ex:
            error = {
                "message": f"Key {idx} was not found on {self.name}",
                "error": str(ex)
            }
            self.error(response=error, status=404)
        finally:
            ## we don't need the ID
            self.model.Meta.connection = None
            await db.release(conn)

    async def get(self):
        """Getting Client information."""
        await self.session()
        ## getting all clients:
        args = self.match_parameters(self.request)
        try:
            if args["meta"] == ":meta":
                # returning JSON schema of Model:
                response = self.model.schema(as_dict=True)
                return self.json_response(response)
            elif args["meta"] == ':sample':
                # return a JSON sample of data:
                response = self.model.sample()
                return self.json_response(response)
        except KeyError:
            pass
        ## getting first the id from params or data:
        try:
            objid = self.get_primary(args)
        except (TypeError, KeyError):
            objid = None
        qp = self.query_parameters(request=self.request)
        try:
            fields = qp['fields'].split(',')
            del qp['fields']
        except KeyError:
            fields = None
        if objid:
            result = await self._get_object_by_id(objid)
            return await self._post_get(result, fields=fields)
        else:
            data = self.query_parameters(self.request)
            try:
                db = self.request.app["database"]
                async with await db.acquire() as conn:
                    self.model.Meta.connection = conn
                    if data:
                        result = await self.model.filter(**data)
                    else:
                        result = await self.model.all()
                    return await self._post_get(result, fields=fields)
            except ModelError as ex:
                error = {
                    "error": f"Missing Info for Model {self.name}",
                    "payload": str(ex)
                }
                return self.error(response=error, status=400)
            except ValidationError as ex:
                error = {
                    "error": f"Unable to load {self.name} info from Database",
                    "payload": ex.payload,
                }
                return self.error(response=error, status=400)
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

    async def _get_data(
        self,
        session: Optional[Any] = None,
        request: web.Request = None
    ) -> Any:
        """_get_data.

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
                        request=request
                    )
        try:
            data = await self.json_data()
            if isinstance(data, list):
                for element in data:
                    await set_column_value(element)
            elif isinstance(data, dict):
                await set_column_value(data)
            else:
                self.error(
                    reason=f"Invalid Data Format: {type(data)}", status=400
                )
        except (TypeError, ValueError, NavException) as ex:
            self.error(
                reason=f"Invalid {self.name} Data: {ex}", status=400
            )
        return data

    def get_primary(self, data: dict) -> Any:
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
                except (TypeError, KeyError):
                    try:
                        objid = data["id"]
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
                reason=f"Invalid PK definition for {self.name}: {self.pk}", status=410
            )

    async def _post_data(self, result, status: int = 200) -> web.Response:
        """_post_data.

        Post-processing data after saved and before summit.
        """
        return self.json_response(result, status=status)

    async def _patch_data(self, result, status: int = 202) -> web.Response:
        """_patch_data.

        Post-processing data after saved and before summit.
        """
        return self.json_response(result, status=status)

    async def put(self):
        """Creating Client information."""
        session = await self.session()
        ### get POST Data:
        data = await self._get_data(
            session=session,
            request=self.request
        )
        ## validate directly with model:
        if isinstance(data, list):
            db = self.request.app["database"]
            async with await db.acquire() as conn:
                self.model.Meta.connection = conn
                try:
                    result = await self.model.create(data)
                    return await self._post_data(result, status=201)
                except DriverError as ex:
                    return self.error(
                        reason=f"Bulk Insert Error: {ex}",
                        status=410,
                    )
        try:
            resultset = self.model(**data)  # pylint: disable=E1102
            db = self.request.app["database"]
            async with await db.acquire() as conn:
                resultset.Meta.connection = conn
                result = await resultset.insert()
                return await self._post_data(result, status=201)
        except StatementError as ex:
            error = {
                "message": f"Cannot Insert, duplicated {self.name}",
                "error": str(ex)
            }
            return self.error(response=error, status=400)
        except ModelError as ex:
            error = {
                "message": f"Unable to insert {self.name}",
                "error": str(ex)
            }
            return self.error(response=error, status=400)
        except ValidationError as ex:
            error = {
                "error": f"Unable to insert {self.name} info",
                "payload": ex.payload,
            }
            return self.error(response=error, status=400)
        except (TypeError, AttributeError, ValueError) as ex:
            error = {
                "error": f"Invalid payload for {self.name}",
                "payload": str(ex),
            }
            return self.error(response=error, status=406)

    async def patch(self):
        """Patch an existing Client or retrieve the column names."""
        session = await self.session()
        ### get session Data:
        params = self.match_parameters()
        try:
            if params["meta"] == ":meta":
                ## returning the columns on Model:
                fields = self.model.__fields__
                return self.json_response(fields)
        except KeyError:
            pass
        data = await self._get_data(
            session=session,
            request=self.request
        )
        ## validate directly with model:
        ## getting first the id from params or data:
        try:
            objid = self.get_primary(data)
        except (TypeError, KeyError):
            try:
                objid = self.get_primary(params)
            except (TypeError, KeyError):
                self.error(
                    reason=f"Invalid Data Primary Key: {self.name}",
                    status=400
                )
        db = self.request.app["database"]
        if objid:
            ## getting client
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
                            try:
                                _filter = {field: entry[field] for field in pk}
                            except KeyError:
                                continue
                            obj = await self.model.get(**_filter)
                            for key, val in entry.items():
                                if key in obj.get_fields():
                                    obj.set(key, val)
                            result.append(await obj.update())
                        return await self._patch_data(result, status=202)
                    else:
                        args = {self.pk: objid}
                        result = await self.model.get(**args)
                        for key, val in data.items():
                            if key in result.get_fields():
                                result.set(key, val)
                        result = await result.update()
                    return await self._patch_data(result, status=202)
                except NoDataFound:
                    headers = {"x-error": f"{self.name} was not Found"}
                    self.no_content(headers=headers)
                if not result:
                    headers = {"x-error": f"{self.name} was not Found"}
                    self.no_content(headers=headers)
        else:
            self.error(reason=f"Invalid {self.name} Data", status=400)

    async def post(self):
        """Create or Update a Client."""
        session = await self.session()
        ### get session Data:
        params = self.match_parameters()
        data = await self._get_data(
            session=session,
            request=self.request
        )
        ## validate directly with model:
        ## getting first the id from params or data:
        try:
            objid = self.get_primary(data)
        except (TypeError, KeyError):
            try:
                objid = self.get_primary(params)
            except (TypeError, KeyError):
                self.error(
                    reason=f"Invalid Data Primary Key: {self.name}",
                    status=400
                )
        db = self.request.app["database"]
        if objid:
            if isinstance(data, dict):
                async with await db.acquire() as conn:
                    self.model.Meta.connection = conn
                    # look for this client, after, save changes
                    error = {"error": f"{self.name} was not Found"}
                    if isinstance(objid, list):
                        try:
                            result = await self.model.updating(_filter=objid, **data)
                            return await self._post_data(result, status=202)
                        except ModelError as ex:
                            error = {
                                "error": f"Missing Info for Model {self.name}",
                                "payload": str(ex)
                            }
                            return self.error(response=error, status=400)
                    else:
                        try:
                            args = {self.pk: objid}
                            result = await self.model.get(**args)
                        except ModelError as ex:
                            error = {
                                "error": f"Missing Info for Model {self.name}",
                                "payload": str(ex)
                            }
                            return self.error(response=error, status=400)
                        except NoDataFound:
                            self.error(response=error, status=400)
                        if not result:
                            self.error(response=error, status=400)
                        ## saved with new changes:
                        for key, val in data.items():
                            if key in result.get_fields():
                                result.set(key, val)
                        try:
                            data = await result.update()
                        except ModelError as ex:
                            error = {
                                "message": f"Invalid {self.name}",
                                "error": str(ex),
                            }
                            return self.error(response=error, status=406)
                        return await self._post_data(data, status=202)
            elif isinstance(data, list):
                async with await db.acquire() as conn:
                    self.model.Meta.connection = conn
                    ### iterate over all elements in data:
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
                            # result.append(data)
                        except ModelError as ex:
                            error = {
                                "message": f"Invalid {self.name}",
                                "error": str(ex),
                            }
                            return self.error(response=error, status=406)
                    return await self._post_data(result, status=202)
        else:
            # create a new client based on data:
            try:
                resultset = self.model(**data)  # pylint: disable=E1102
                async with await db.acquire() as conn:
                    resultset.Meta.connection = conn
                    result = await resultset.insert()  # TODO: migrate to use save()
                    return await self._post_data(data, status=201)
            except ModelError as ex:
                error = {
                    "error": f"Missing Info for Model {self.name}",
                    "payload": str(ex)
                }
                return self.error(response=error, status=400)
            except ValidationError as ex:
                error = {
                    "error": f"Unable to insert {self.name} info",
                    "payload": str(ex.payload),
                }
                return self.error(response=error, status=400)
            except (TypeError, AttributeError, ValueError) as ex:
                error = {
                    "error": f"Invalid payload for {self.name}",
                    "payload": str(ex),
                }
                return self.error(response=error, status=406)

    async def _get_del_data(
        self,
        session: Optional[Any] = None,
        request: web.Request = None
    ) -> Any:
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
                    data[name] = await fn(value=val, column=column, request=request)
        except (TypeError, ValueError, NavException):
            pass
        return data

    async def delete(self):
        """Delete a Client."""
        session = await self.session()
        ### get session Data:
        params = self.match_parameters()
        data = await self._get_del_data(session=session)
        ## getting first the id from params or data:
        try:
            objid = self.get_primary(data)
        except (TypeError, KeyError):
            try:
                objid = self.get_primary(params)
            except (TypeError, KeyError):
                self.error(
                    reason=f"Invalid Data Primary Key: {self.name}",
                    status=400
                )
        if objid:
            db = self.request.app["database"]
            try:
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
                        return self.json_response(data, status=202)
                    except NoDataFound:
                        error = {
                            "message": f"Key {objid} was not found on {self.name}",
                        }
                        return self.error(response=error, status=404)
            except Exception as ex:
                error = {
                    "message": f"Key {objid} was not found on {self.name}",
                    "error": str(ex)
                }
                self.error(response=error, status=404)
        else:
            self.error(
                reason=f"Cannot Delete an Empty {self.name}",
                status=400
            )
