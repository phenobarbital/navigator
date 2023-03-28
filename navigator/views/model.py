import traceback
from aiohttp import web
from asyncdb.models import Model
from asyncdb.exceptions import DriverError, NoDataFound
from navconfig.logging import logger
from navigator.exceptions import NavException
from .base import BaseView


async def load_models(app: str, model, tablelist: list):
    pool = app["database"]
    async with await pool.acquire() as conn:
        name = app["name"]
        if isinstance(tablelist, list):
            for table in tablelist:
                try:
                    query = await Model.makeModel(name=table, schema=name, db=conn)
                    model[table] = query
                except Exception as err:  # pylint: disable=W0703
                    logger.error(f"Error loading Model {table}: {err!s}")
            return model


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

    model: Model = None

    def __init__(self, request, *args, **kwargs):
        # self.model: Model = None
        self.models: dict = {}
        super(ModelView, self).__init__(request, *args, **kwargs)
        # getting model associated
        try:
            self.model = self.get_schema()
        except NoDataFound as err:
            raise NavException(
                f"Error on Getting Model {self.model}: {err}"
            ) from err

    def get_schema(self):
        if self.model:
            return self.model
        else:
            # TODO: try to discover from Model Name and model declaration
            # using importlib (from apps.{program}.models import Model)
            try:
                table = self.Meta.tablename
            except Exception as err:  # pylint: disable=W0703
                print(err)
                table = type(self).__name__
                self.Meta.tablename = table
            try:
                return self.models[table]
            except KeyError as err:
                # Model doesn't exists
                raise NoDataFound(
                    f"Model {table} Doesn't Exists"
                ) from err

    async def get_connection(self, driver: str = "database"):
        try:
            if not self.model.Meta.connection:
                self._connection = self.request.app[driver].acquire()
                self.model.Meta.connection = self._connection
        except Exception as err:
            raise NavException(
                f"ModelView Error: Cannot get Connection: {err}"
            ) from err

    async def get_data(self, params, args):
        db = self.request.app["database"]
        data = None
        async with await db.acquire() as conn:
            self.model.Meta.connection = conn
            try:
                if len(params) > 0:
                    print("FILTER")
                    query = await self.model.filter(**params)
                elif len(args) > 0:
                    print("GET")
                    query = await self.model.get(**args)
                    return query.dict()
                else:
                    print("ALL")
                    query = await self.model.all()
                if query:
                    data = [row.dict() for row in query]
                else:
                    raise NoDataFound('No Data was found')
            except NoDataFound:
                raise
            except Exception as err:
                raise NavException(
                    f"Error getting data from Model: {err}"
                ) from err
        await db.release(conn)
        return data



    def model_response(self, response, headers: dict = None):
        # TODO: check if response is empty
        if not response:
            return self.no_content(headers=headers)
        # return data only
        return self.json_response(response, headers=headers)

    def get_args(self, request: web.Request = None) -> dict:
        params = {}
        if not request:
            rq = self.request
        else:
            rq = request
        for arg in rq.match_info:
            try:
                val = rq.match_info.get(arg)
                object.__setattr__(self, arg, val)
                params[arg] = val
            except AttributeError:
                pass
        return params

    async def get_parameters(self):
        """Get Parameters.

        Get all parameters from URL or from query string.
        """
        args = self.get_args()
        params = self.query_parameters(self.request)
        return [args, params]

    async def get(self):
        args, params = await self.get_parameters()
        # TODO: check if QueryParameters are in list of columns in Model
        try:
            data = await self.get_data(params, args)
            return self.model_response(data)
        except NoDataFound:
            headers = {
                "X-STATUS": "EMPTY",
                "X-MESSAGE": f"Data on {self.Meta.tablename} not Found",
            }
            return self.no_content(headers=headers)
        except DriverError as err:
            return self.critical(
                request=self.request, exception=err, stacktrace=""
            )

    async def patch(self):
        """
        patch.
            summary: return the metadata from table or, if we got post
            realizes a partially atomic updated of the query.
        """
        args, _ = await self.get_parameters()
        # try to got post data
        post = await self.json_data()
        if post:
            db = self.request.app["database"]
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                # trying to update the model
                update = await self.model.update(args, **post)
                if update:
                    data = update[0].dict()
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Resource not found: {post}",
                        request=self.request,
                        state=404,
                    )
        else:
            try:
                # getting metadata of Model
                qry = self.model(**args)
                data = {}
                for _, field in qry.columns().items():
                    key = field.name
                    _type = field.db_type()
                    default = None
                    if field.default is not None:
                        default = f"{field.default!r}"
                    data[key] = {"type": _type, "default": default}
                return self.model_response(data)
            except Exception as err:  # pylint: disable=W0703
                stack = traceback.format_exc()
                return self.critical(
                    request=self.request, exception=err, stacktrace=stack
                )

    async def post(self):
        """
        post.
            summary: update (or create) a row in table
        """
        args, _ = await self.get_parameters()
        post = await self.json_data()
        if not post:
            return self.error(
                request=self.request,
                response="Cannot Update row without JSON Data",
                state=406,
            )
        db = self.request.app["database"]
        # updating several at the same time:
        if isinstance(post, list):
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                # mass-update using arguments:
                try:
                    result = self.model.update(args, **post)
                    data = [row.dict() for row in result]
                    return self.model_response(data)
                except Exception as err:  # pylint: disable=W0703
                    trace = traceback.format_exc()
                    return self.critical(
                        request=self.request, exception=err, stacktrace=trace
                    )
        if len(args) > 0:
            parameters = {**args, **post}
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                try:
                    # check if exists first:
                    query = await self.model.get(**args)
                    if not query:
                        # object doesnt exists, need to be created:
                        result = await self.model.create([parameters])
                        query = await self.model.get(**parameters)
                        data = query.dict()
                        return self.model_response(data)
                except Exception as err:  # pylint: disable=W0703
                    print(err)
                    return self.error(
                        response=f"Error Saving Data {err!s}"
                    )
        # I need to use post data only
        try:
            db = self.request.app["database"]
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                qry = self.model(**post)
                if qry.is_valid():
                    await qry.save()
                    query = await qry.fetch(**args)
                    data = query.dict()
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Invalid data for Schema {self.Meta.tablename}",
                    )
        except Exception as err:  # pylint: disable=W0703
            print(err)
            trace = traceback.format_exc()
            return self.critical(exception=err, stacktrace=trace)

    async def delete(self):
        """ "
        delete.
           summary: delete a table object
        """
        args, params = await self.get_parameters()
        db = self.request.app["database"]
        try:
            result = None
            async with await db.connection() as conn:
                self.model.Meta.connection = conn
                if len(args) > 0:
                    # need to delete one
                    result = await self.model.remove(args)
                elif len(params) > 0:
                    result = await self.model.remove(params)
        except Exception as err:  # pylint: disable=W0703
            return self.error(
                request=self.request,
                response="Error Deleting Object",
                exception=err,
                state=400,
            )
        if result is not None:
            msg = {"result": result}
            headers = {
                "X-STATUS": "OK",
                "X-MESSAGE": f"Table row was deleted: {self.model!r}",
                "X-TABLE": self.Meta.tablename,
            }
            return self.model_response(msg, headers=headers)
        else:
            headers = {
                "X-STATUS": "Error",
                "X-MESSAGE": f"Row in Table {self.Meta.tablename} not deleted",
            }
            return self.error(
                response=f"Row in Table {self.Meta.tablename} not deleted",
                headers=headers,
                state=404,
            )

    async def put(self):
        """ "
        put.
           summary: insert a row in table
        """
        _, params = await self.get_parameters()
        post = await self.json_data()
        if not post:
            return self.error(
                request=self.request,
                response="Cannot Insert a row without post data",
                state=406,
            )
        parameters = {**params, **post}
        db = self.request.app["database"]
        async with await db.connection() as conn:
            self.model.Meta.connection = conn
            try:
                qry = self.model(**parameters)
                if qry.is_valid():
                    # TODO: if insert fails in constraint, trigger POST (UPDATE)
                    result = await self.model.create([parameters])
                    if result:
                        data = [row.dict() for row in result]
                    return self.model_response(data)
                else:
                    return self.error(
                        response=f"Invalid data for Schema {self.Meta.tablename}",
                    )
            except DriverError as err:
                stack = traceback.format_exc()
                return self.critical(exception=err, stacktrace=stack)
            except Exception as err:  # pylint: disable=W0703
                stack = traceback.format_exc()
                return self.critical(
                    exception=err, stacktrace=stack, state=501
                )

    class Meta:
        tablename: str = ""
