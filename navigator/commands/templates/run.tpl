#!/usr/bin/env python3
from navigator import Application
from app import Main

# define new Application
app = Application(Main)

# Enable WebSockets Support
app.add_websockets()

if __name__ == '__main__':
    app.run()
