from typing import Union, Any
from collections.abc import Callable
from functools import wraps
import asyncio
import inspect
from dataclasses import dataclass, is_dataclass
from aiohttp import web
from aiohttp.abc import AbstractView
from aiohttp.web_exceptions import HTTPError
from datamodel import BaseModel
from datamodel.exceptions import ValidationError
from navigator_auth.conf import exclude_list


"""
Useful decorators for the navigator app.
"""
def allow_anonymous(func):
    """
    allow_anonymous.

    Add this path to exclude_list to bypass auth.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if inspect.isclass(func) and issubclass(func, AbstractView):
            request = args[0]
        else:
            request = args[-1]
        path = request.path
        exclude_list.add(path)  # Add this path to exclude_list to bypass auth
        return await func(*args, **kwargs)
    return wrapper


async def validate_model(request: web.Request, model: Union[dataclass, BaseModel]) -> tuple:
    """
    validate_model.

    Description: Validate a model using a dataclass or BaseModel.
    Args:
        request (web.Request): aiohttp Request object.
        model (Union[dataclass,BaseModel]): Model can be a dataclass or BaseModel.

    Returns:
        tuple: data, errors (if any)
    """
    errors: dict = {}
    data = None
    if request.method in ('OPTIONS', 'HEAD'):
        # There is no validation for OPTIONS/HEAD methods:
        return (True, None)
    elif request.method in ("POST", "PUT", "PATCH"):
        if request.content_type == "application/json":
            # getting data from POST
            data = await request.json()
        else:
            data = await request.post()
    elif request.method == "GET":
        data = {key: val for (key, val) in request.query.items()}
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

    async def validate_data(data):
        valid = None
        errors = {}
        if issubclass(model, BaseModel):
            try:
                valid = model(**data)
            except (TypeError, ValueError, AttributeError) as exc:
                errors = {
                    "error": f"Invalid Data: {exc}"
                }
            except ValidationError as exc:
                errors = {
                    "error": f"Invalid Data: {exc}",
                    "payload": exc.payload
                }
        elif is_dataclass(model):
            try:
                valid = model(**data)
            except Exception as err:
                errors = {"error": f"Invalid Data: {err}"}
        else:
            errors = {"error": "Invalid Model Type"}
        return valid, errors

    errors = {}
    valid = {}

    if isinstance(data, dict):
        if isinstance(list(data.values())[0], dict):
            for k, v in data.items():
                item_valid, item_error = await validate_data(v)
                if item_valid:
                    valid[k] = item_valid
                if item_error:
                    errors.update(item_error)
            if valid:
                return valid, errors
        valid, error = await validate_data(data)
        if error:
            errors.update(error)
        return valid, errors

    elif isinstance(data, list):
        valid = []
        for item in data:
            item_valid, item_error = await validate_data(item)
            if item_valid:
                valid.append(item_valid)
            if item_error:
                errors.update(item_error)
        return valid, errors
    else:
        return data, {
            "error": "Invalid type for Data Input, expecting a Dict or List."
        }


def validate_payload(*models: Union[type[BaseModel], type[dataclass]]) -> Callable:
    """validate_payload.
    Description: Validate Request payload using dataclasses or Datamodels.
    Args:
        models (Union[dataclass,BaseModel]): List of models can be used for validation.
        kwargs: Any other data passed as arguments to function.

    Returns:
        Callable: Decorator function adding validated data to handler.
    """
    def _validation(func: Callable) -> Callable:
        @wraps(func)
        async def _wrap(*args: Any, **kwargs) -> web.StreamResponse:
            ## building arguments:
            # Supports class based views see web.View
            if isinstance(args[0], AbstractView):
                request = args[0].request
            elif isinstance(args[0], web.View):
                request = args[0].request
            else:
                request = args[-1]

            content_type = request.headers.get('Content-Type')

            sig = inspect.signature(func)
            bound_args = sig.bind_partial(*args, **kwargs)
            bound_args.apply_defaults()

            # Dictionary to hold validation results
            validated_data = {}
            errors = {}

            # Validate payload using the model
            for model in models:
                try:
                    data, model_errors = await validate_model(
                        request, model
                    )
                    model_name = model.__name__.lower()
                    validated_data[model_name] = data
                    if model_errors:
                        errors[model_name] = model_errors
                except Exception as err:
                    if content_type == "application/json":
                        return web.json_response(
                            {
                                "error": f"Error during validation of model {model.__name__}: {err}"
                            }, status=400
                        )
                    raise web.HTTPBadRequest(
                        reason=f"Error during validation of model {model.__name__}: {err}",
                        content_type="application/json"
                    )

            # Assign validated data to respective function arguments
            for param_name, param in sig.parameters.items():
                model_name = param_name.lower()
                if model_name in validated_data:
                    bound_args.arguments[param_name] = validated_data[model_name]

            bound_args.arguments['errors'] = errors

            # Call the original function with new arguments
            try:
                if asyncio.iscoroutinefunction(func):
                    response = await func(*bound_args.args, **bound_args.kwargs)
                else:
                    response = func(*bound_args.args, **bound_args.kwargs)
                return response
            except HTTPError as ex:
                return ex
            except Exception as err:
                if content_type == "application/json":
                    return web.json_response(
                        {"error": str(err)}, status=500
                    )
                raise web.HTTPInternalServerError(
                    reason=f"Error Calling Function {func.__name__}: {err}"
                ) from err

        return _wrap

    return _validation
