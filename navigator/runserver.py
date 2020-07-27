#!/usr/bin/env python3
import sys
from navigator import Application
from aiohttp import web
from app import Main
obj = Application(Main, debug=True)

# declaring auto-reload on debug
app = obj.setup_app()

if __name__ == '__main__':
    obj.run()
