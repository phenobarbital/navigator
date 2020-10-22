#!/usr/bin/env python3
from app import Main

from navigator import Application, Response

# define new Application
app = Application(Main)

# Enable WebSockets Support
app.add_websockets()

if __name__ == '__main__':
    app.run()
