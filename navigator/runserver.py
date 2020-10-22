#!/usr/bin/env python3
import sys

from aiohttp import web
from app import Main

from navigator import Application

obj = Application(Main, debug=True)

# declaring auto-reload on debug
app = obj.setup_app()

if __name__ == "__main__":
    obj.run()
