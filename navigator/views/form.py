from typing import Union, Any
from datamodel.exceptions import ValidationError
from .abstract import AbstractModel


class FormModel(AbstractModel):
    """FormModel.

    Form Model, creates an arbitrary Form using a BaseModel.
    """
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
        return await self._get_form(args, qp, fields)

    async def _get_form(self, args, qp, fields):
        """Get Form information."""
        pass
