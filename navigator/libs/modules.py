from abc import abstractmethod
from textwrap import dedent

from aiohttp import web


class AbstractHandler:
    _template = "<!doctype html><head></head><body></body>"

    def __init__(self):
        self._template = dedent(self._template)

    async def index(self, request: web.Request):  # pylint: disable=W0613
        response = web.Response(body="")
        return response

    def html_response(self, text: str):
        return web.Response(text=text, content_type="text/html")

    @abstractmethod
    async def configure(self, app):
        pass
