from typing import Any, TypeVar, Union
from collections.abc import Callable
from pathlib import PurePath
from functools import wraps
import inspect
from aiohttp import web
from aiohttp.abc import AbstractView
from .parser import TemplateParser
from ..libs.json import json_decoder


F = TypeVar("F", bound=Callable[..., Any])


def use_template(
    template: Union[str, PurePath],
    content_type: str = "text/html",
    encoding: str = "utf-8"
) -> Callable[[F], F]:
    """
    use_template.

    Decorator for adding a Jinja template as renderer for a handler/view.
    """
    def _wrapper(handler: F):
        @wraps(handler)
        async def _wrap(*args, **kwargs) -> web.StreamResponse:
            # Supports class based views see web.View
            _is_view: bool = False
            if inspect.isclass(handler) and issubclass(handler, AbstractView):
                _is_view = True
                request = args[0]
            else:
                request = args[-1]
            if request is None:
                raise web.HTTPBadRequest(
                    reason="No request object available.",
                    content_type=content_type
                )
            # extracting app and ensure the template system is initialized
            try:
                tmpl: TemplateParser = request.app["template"]  # template system
            except KeyError as e:
                raise web.HTTPBadRequest(
                    reason="NAV Template system is not initialized in the app.",
                    content_type=content_type
                ) from e
            # Execute the handler
            result = await handler(*args, **kwargs)
            # Prepare the context for the template
            if isinstance(result, web.StreamResponse):
                # If the handler returns a StreamResponse, attempt to extract the body for rendering
                body = result.body
                try:
                    context = json_decoder(body)
                except Exception:
                    context = {'result': body}  # If not JSON, use raw body as result
            elif isinstance(result, dict):
                context = result
            else:
                # Convert other types of responses to dict if needed
                context = {'result': result}
            if kwargs:
                context = {**context, **kwargs}
            # prepare the template:
            try:
                try:
                    response_text = await tmpl.render(template, params=context)
                except FileNotFoundError:
                    # is not a template file
                    response_text = await tmpl.string_render(template, params=context)
            except (ValueError, RuntimeError) as e:
                raise web.HTTPInternalServerError(
                    reason=f"Error parsing Template '{template}': {e}",
                    content_type=content_type
                ) from e
            return web.Response(
                body=response_text,
                content_type=content_type,
                charset=encoding,
                **kwargs
            )

        return _wrap

    return _wrapper
